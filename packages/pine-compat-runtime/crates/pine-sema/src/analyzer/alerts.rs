use crate::prelude::*;

fn unsupported_alert_placeholder(value: &str, supported: &[&str]) -> Option<String> {
    let mut remaining = value;
    while let Some(start) = remaining.find("{{") {
        let placeholder_tail = &remaining[start..];
        let Some(relative_end) = placeholder_tail.find("}}") else {
            return Some("{{".to_owned());
        };
        let end = relative_end + 2;
        let placeholder = &placeholder_tail[..end];
        if !supported.contains(&placeholder) {
            return Some(placeholder.to_owned());
        }
        remaining = &placeholder_tail[end..];
    }
    None
}

fn is_supported_alert_frequency(value: &str) -> bool {
    matches!(
        value,
        "alert.freq_all" | "alert.freq_once_per_bar" | "alert.freq_once_per_bar_close"
    )
}

impl Analyzer {
    pub(crate) fn validate_alert_args(&mut self, signature: &BuiltinSignature, args: &[CallArg]) {
        if !matches!(signature.name, "alert" | "alertcondition") {
            return;
        }

        for (index, arg) in args.iter().enumerate() {
            let Some(param_name) = self
                .resolve_param(signature, index, arg)
                .map(|param| param.name)
            else {
                continue;
            };

            if signature.name == "alert" && param_name == "freq" {
                let supported = self
                    .known_const_string_value(&arg.value)
                    .as_deref()
                    .is_some_and(is_supported_alert_frequency);
                if !supported {
                    self.unsupported(
                        "alert_frequency",
                        "only alert.freq_all, alert.freq_once_per_bar, and alert.freq_once_per_bar_close are supported in the current alert frequency subset",
                        arg.span,
                    );
                }
            }

            if matches!(param_name, "message" | "title") {
                let supported_placeholders =
                    if signature.name == "alertcondition" && param_name == "message" {
                        &[
                            "{{open}}",
                            "{{high}}",
                            "{{low}}",
                            "{{close}}",
                            "{{volume}}",
                            "{{ticker}}",
                            "{{interval}}",
                            "{{exchange}}",
                            "{{time}}",
                        ][..]
                    } else {
                        &[][..]
                    };

                if let Some(placeholder) = self
                    .known_const_string_value(&arg.value)
                    .as_deref()
                    .and_then(|value| unsupported_alert_placeholder(value, supported_placeholders))
                {
                    self.unsupported(
                        "alert_placeholders",
                        &format!(
                            "alert placeholder `{placeholder}` is not supported in the current alert subset"
                        ),
                        arg.span,
                    );
                }
            }
        }
    }
}
