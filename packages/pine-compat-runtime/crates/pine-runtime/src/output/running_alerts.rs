use std::fmt;

use serde::{Deserialize, Serialize};

use super::strategy::StrategyOrderFillAlertOutput;
use super::strategy_alert_templates::{
    StrategyOrderFillAlertTemplateError, render_strategy_order_fill_alert_template,
};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum RunningAlertEventSelection {
    IndicatorAlertCalls,
    StrategyOrderFills,
    Both,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum RunningAlertRealtimePolicy {
    RealtimeOnly,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RunningAlertConfig {
    pub script_snapshot_id: String,
    pub symbol: String,
    pub timeframe: String,
    pub event_selection: RunningAlertEventSelection,
    pub message_template: String,
    pub realtime_policy: RunningAlertRealtimePolicy,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RunningAlertEvaluationError {
    UnsupportedEventSelection {
        selection: RunningAlertEventSelection,
    },
    Template(StrategyOrderFillAlertTemplateError),
}

impl fmt::Display for RunningAlertEvaluationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnsupportedEventSelection { selection } => write!(
                formatter,
                "running alert event selection `{}` cannot evaluate a strategy order-fill event",
                selection.as_str()
            ),
            Self::Template(error) => error.fmt(formatter),
        }
    }
}

impl std::error::Error for RunningAlertEvaluationError {}

impl From<StrategyOrderFillAlertTemplateError> for RunningAlertEvaluationError {
    fn from(error: StrategyOrderFillAlertTemplateError) -> Self {
        Self::Template(error)
    }
}

impl RunningAlertEventSelection {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::IndicatorAlertCalls => "indicatorAlertCalls",
            Self::StrategyOrderFills => "strategyOrderFills",
            Self::Both => "both",
        }
    }
}

impl RunningAlertConfig {
    pub fn new_strategy_order_fills(
        script_snapshot_id: impl Into<String>,
        symbol: impl Into<String>,
        timeframe: impl Into<String>,
        message_template: impl Into<String>,
    ) -> Self {
        Self {
            script_snapshot_id: script_snapshot_id.into(),
            symbol: symbol.into(),
            timeframe: timeframe.into(),
            event_selection: RunningAlertEventSelection::StrategyOrderFills,
            message_template: message_template.into(),
            realtime_policy: RunningAlertRealtimePolicy::RealtimeOnly,
        }
    }
}

pub fn render_strategy_order_fill_running_alert(
    config: &RunningAlertConfig,
    alert: &StrategyOrderFillAlertOutput,
) -> Result<String, RunningAlertEvaluationError> {
    if config.event_selection != RunningAlertEventSelection::StrategyOrderFills {
        return Err(RunningAlertEvaluationError::UnsupportedEventSelection {
            selection: config.event_selection.clone(),
        });
    }

    render_strategy_order_fill_alert_template(&config.message_template, alert).map_err(Into::into)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn alert(message: &str) -> StrategyOrderFillAlertOutput {
        StrategyOrderFillAlertOutput {
            id: "XL".to_owned(),
            bar_index: 1,
            time: 2,
            direction: "strategy.exit".to_owned(),
            qty: 3.0,
            price: 4.0,
            entry_id: Some("L".to_owned()),
            exit_id: Some("XL".to_owned()),
            message: message.to_owned(),
        }
    }

    #[test]
    fn strategy_order_fill_constructor_sets_realtime_only_boundary() {
        let config = RunningAlertConfig::new_strategy_order_fills(
            "snapshot-1",
            "NASDAQ:AAPL",
            "60",
            "Order: {{strategy.order.alert_message}}",
        );

        assert_eq!(config.script_snapshot_id, "snapshot-1");
        assert_eq!(config.symbol, "NASDAQ:AAPL");
        assert_eq!(config.timeframe, "60");
        assert_eq!(
            config.event_selection,
            RunningAlertEventSelection::StrategyOrderFills
        );
        assert_eq!(
            config.message_template,
            "Order: {{strategy.order.alert_message}}"
        );
        assert_eq!(
            config.realtime_policy,
            RunningAlertRealtimePolicy::RealtimeOnly
        );
    }

    #[test]
    fn serializes_stable_host_owned_shape() {
        let config = RunningAlertConfig::new_strategy_order_fills(
            "snapshot-1",
            "NASDAQ:AAPL",
            "60",
            "Order: {{strategy.order.alert_message}}",
        );

        let json = serde_json::to_value(&config).expect("config should serialize");

        assert_eq!(
            json,
            serde_json::json!({
                "scriptSnapshotId": "snapshot-1",
                "symbol": "NASDAQ:AAPL",
                "timeframe": "60",
                "eventSelection": "strategyOrderFills",
                "messageTemplate": "Order: {{strategy.order.alert_message}}",
                "realtimePolicy": "realtimeOnly"
            })
        );
    }

    #[test]
    fn deserializes_all_documented_event_selection_variants() {
        let selections = [
            (
                "indicatorAlertCalls",
                RunningAlertEventSelection::IndicatorAlertCalls,
            ),
            (
                "strategyOrderFills",
                RunningAlertEventSelection::StrategyOrderFills,
            ),
            ("both", RunningAlertEventSelection::Both),
        ];

        for (selection_json, expected) in selections {
            let config: RunningAlertConfig = serde_json::from_value(serde_json::json!({
                "scriptSnapshotId": "snapshot-1",
                "symbol": "NASDAQ:AAPL",
                "timeframe": "60",
                "eventSelection": selection_json,
                "messageTemplate": "Order: {{strategy.order.alert_message}}",
                "realtimePolicy": "realtimeOnly"
            }))
            .expect("config should deserialize");

            assert_eq!(config.event_selection, expected);
        }
    }

    #[test]
    fn renders_strategy_order_fill_running_alert() {
        let config = RunningAlertConfig::new_strategy_order_fills(
            "snapshot-1",
            "NASDAQ:AAPL",
            "60",
            "Order: {{strategy.order.alert_message}}",
        );

        let output = render_strategy_order_fill_running_alert(&config, &alert("exit alert"))
            .expect("strategy order-fill running alert should render");

        assert_eq!(output, "Order: exit alert");
    }

    #[test]
    fn rejects_indicator_only_selection_for_strategy_order_fill_event() {
        let mut config = RunningAlertConfig::new_strategy_order_fills(
            "snapshot-1",
            "NASDAQ:AAPL",
            "60",
            "Order: {{strategy.order.alert_message}}",
        );
        config.event_selection = RunningAlertEventSelection::IndicatorAlertCalls;

        let error = render_strategy_order_fill_running_alert(&config, &alert("exit alert"))
            .expect_err("indicator-only selection should not handle order-fill event");

        assert_eq!(
            error,
            RunningAlertEvaluationError::UnsupportedEventSelection {
                selection: RunningAlertEventSelection::IndicatorAlertCalls,
            }
        );
    }

    #[test]
    fn keeps_both_selection_design_only_until_shared_event_envelope_exists() {
        let mut config = RunningAlertConfig::new_strategy_order_fills(
            "snapshot-1",
            "NASDAQ:AAPL",
            "60",
            "Order: {{strategy.order.alert_message}}",
        );
        config.event_selection = RunningAlertEventSelection::Both;

        let error = render_strategy_order_fill_running_alert(&config, &alert("exit alert"))
            .expect_err("both selection needs a shared event envelope first");

        assert_eq!(
            error,
            RunningAlertEvaluationError::UnsupportedEventSelection {
                selection: RunningAlertEventSelection::Both,
            }
        );
    }

    #[test]
    fn reports_template_errors_as_host_evaluation_errors() {
        let config = RunningAlertConfig::new_strategy_order_fills(
            "snapshot-1",
            "NASDAQ:AAPL",
            "60",
            "{{close}}",
        );

        let error = render_strategy_order_fill_running_alert(&config, &alert("exit alert"))
            .expect_err("unsupported host placeholder should fail");

        assert_eq!(
            error,
            RunningAlertEvaluationError::Template(
                StrategyOrderFillAlertTemplateError::UnsupportedPlaceholder {
                    placeholder: "{{close}}".to_owned(),
                },
            )
        );
    }
}
