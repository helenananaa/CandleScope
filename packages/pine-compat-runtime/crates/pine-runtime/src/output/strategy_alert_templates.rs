use std::fmt;

use super::strategy::StrategyOrderFillAlertOutput;

pub const STRATEGY_ORDER_ALERT_MESSAGE_PLACEHOLDER: &str = "{{strategy.order.alert_message}}";

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StrategyOrderFillAlertTemplateError {
    UnsupportedPlaceholder { placeholder: String },
    UnclosedPlaceholder,
}

impl fmt::Display for StrategyOrderFillAlertTemplateError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnsupportedPlaceholder { placeholder } => {
                write!(
                    formatter,
                    "unsupported strategy order-fill alert placeholder `{placeholder}`"
                )
            }
            Self::UnclosedPlaceholder => write!(
                formatter,
                "unclosed strategy order-fill alert placeholder in template"
            ),
        }
    }
}

impl std::error::Error for StrategyOrderFillAlertTemplateError {}

pub fn render_strategy_order_fill_alert_template(
    template: &str,
    alert: &StrategyOrderFillAlertOutput,
) -> Result<String, StrategyOrderFillAlertTemplateError> {
    let mut output = String::new();
    let mut remaining = template;

    while let Some(start) = remaining.find("{{") {
        output.push_str(&remaining[..start]);
        let placeholder_tail = &remaining[start..];
        let Some(relative_end) = placeholder_tail.find("}}") else {
            return Err(StrategyOrderFillAlertTemplateError::UnclosedPlaceholder);
        };
        let end = relative_end + 2;
        let placeholder = &placeholder_tail[..end];
        if placeholder != STRATEGY_ORDER_ALERT_MESSAGE_PLACEHOLDER {
            return Err(
                StrategyOrderFillAlertTemplateError::UnsupportedPlaceholder {
                    placeholder: placeholder.to_owned(),
                },
            );
        }
        output.push_str(&alert.message);
        remaining = &placeholder_tail[end..];
    }

    output.push_str(remaining);
    Ok(output)
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
    fn renders_strategy_order_alert_message_placeholder() {
        let output = render_strategy_order_fill_alert_template(
            "Fill: {{strategy.order.alert_message}}.",
            &alert("exit alert"),
        )
        .expect("template should render");

        assert_eq!(output, "Fill: exit alert.");
    }

    #[test]
    fn renders_empty_strategy_order_alert_message_as_empty_string() {
        let output = render_strategy_order_fill_alert_template(
            "Fill: {{strategy.order.alert_message}}.",
            &alert(""),
        )
        .expect("template should render");

        assert_eq!(output, "Fill: .");
    }

    #[test]
    fn renders_multiple_strategy_order_alert_message_occurrences() {
        let output = render_strategy_order_fill_alert_template(
            "{{strategy.order.alert_message}}/{{strategy.order.alert_message}}",
            &alert("A"),
        )
        .expect("template should render");

        assert_eq!(output, "A/A");
    }

    #[test]
    fn rejects_unknown_placeholders_in_host_template() {
        let error = render_strategy_order_fill_alert_template("{{close}}", &alert("A"))
            .expect_err("unknown placeholder should fail");

        assert_eq!(
            error,
            StrategyOrderFillAlertTemplateError::UnsupportedPlaceholder {
                placeholder: "{{close}}".to_owned(),
            }
        );
    }

    #[test]
    fn rejects_whitespace_variant_placeholder_in_host_template() {
        let error = render_strategy_order_fill_alert_template(
            "{{ strategy.order.alert_message }}",
            &alert("A"),
        )
        .expect_err("whitespace placeholder should fail");

        assert_eq!(
            error,
            StrategyOrderFillAlertTemplateError::UnsupportedPlaceholder {
                placeholder: "{{ strategy.order.alert_message }}".to_owned(),
            }
        );
    }

    #[test]
    fn rejects_unclosed_placeholders_in_host_template() {
        let error = render_strategy_order_fill_alert_template("{{close", &alert("A"))
            .expect_err("unclosed placeholder should fail");

        assert_eq!(
            error,
            StrategyOrderFillAlertTemplateError::UnclosedPlaceholder
        );
    }

    #[test]
    fn does_not_recursively_render_inserted_alert_message() {
        let output = render_strategy_order_fill_alert_template(
            "Fill: {{strategy.order.alert_message}}",
            &alert("{{close}}"),
        )
        .expect("template should render");

        assert_eq!(output, "Fill: {{close}}");
    }

    #[test]
    fn leaves_templates_without_placeholders_unchanged() {
        let output = render_strategy_order_fill_alert_template("plain template", &alert("A"))
            .expect("template should render");

        assert_eq!(output, "plain template");
    }
}
