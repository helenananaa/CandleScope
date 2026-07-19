#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub(crate) struct StrategyOrderMetadata {
    pub(crate) comment: Option<String>,
    pub(crate) alert_message: Option<String>,
    pub(crate) disable_alert: bool,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub(crate) struct StrategyExitMetadata {
    pub(crate) comment: Option<String>,
    pub(crate) comment_profit: Option<String>,
    pub(crate) comment_loss: Option<String>,
    pub(crate) comment_trailing: Option<String>,
    pub(crate) alert_message: Option<String>,
    pub(crate) alert_profit: Option<String>,
    pub(crate) alert_loss: Option<String>,
    pub(crate) alert_trailing: Option<String>,
    pub(crate) disable_alert: bool,
}

#[allow(dead_code)]
#[derive(Debug, Clone, PartialEq)]
pub(crate) struct StrategyOrderFillAlertEvent {
    pub(crate) id: String,
    pub(crate) bar_index: usize,
    pub(crate) time: i64,
    pub(crate) direction: String,
    pub(crate) qty: f64,
    pub(crate) price: f64,
    pub(crate) entry_id: Option<String>,
    pub(crate) exit_id: Option<String>,
    pub(crate) message: String,
}

pub(super) struct EntryFill {
    pub(super) id: String,
    pub(super) bar_index: usize,
    pub(super) time: i64,
    pub(super) price: f64,
    pub(super) qty: f64,
    pub(super) metadata: StrategyOrderMetadata,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum EntryPyramidingMode {
    EnforceLimit,
    BypassLimit,
    SameTickPriceException,
}

#[derive(Debug, Clone, PartialEq)]
pub(super) struct ClosedTradeMetrics {
    pub(super) commission: f64,
    pub(super) profit_percent: f64,
    pub(super) max_runup: f64,
    pub(super) max_drawdown: f64,
    pub(super) entry_comment: Option<String>,
    pub(super) exit_comment: Option<String>,
    pub(super) close_metadata: StrategyOrderMetadata,
}
