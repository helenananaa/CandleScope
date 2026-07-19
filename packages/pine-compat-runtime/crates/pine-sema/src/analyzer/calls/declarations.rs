use crate::prelude::*;

impl Analyzer {
    pub(crate) fn validate_label_string_arg(
        &mut self,
        signature: &BuiltinSignature,
        args: &[CallArg],
        index: usize,
        name: &str,
        allowed: &[&str],
    ) {
        for (arg_index, arg) in args.iter().enumerate() {
            let is_target = arg.name.as_deref() == Some(name)
                || (arg.name.is_none()
                    && signature
                        .params
                        .get(arg_index)
                        .is_some_and(|param| param.name == name && index == arg_index));
            if !is_target {
                continue;
            }
            let Some(value) = self.known_const_string_value(&arg.value) else {
                continue;
            };
            if !allowed.iter().any(|allowed_value| *allowed_value == value) {
                self.diagnostics.push(Diagnostic::error(
                    "E_CALL_ARG_VALUE",
                    format!(
                        "`{}` argument `{name}` only supports {}",
                        signature.name,
                        allowed.join(", ")
                    ),
                    arg.span,
                ));
            }
        }
    }

    pub(crate) fn validate_indicator_args(
        &mut self,
        signature: &BuiltinSignature,
        args: &[CallArg],
    ) {
        if signature.name != "indicator" {
            return;
        }

        self.validate_label_string_arg(
            signature,
            args,
            3,
            "format",
            &[
                "format.inherit",
                "format.price",
                "format.percent",
                "format.volume",
            ],
        );
        self.validate_label_string_arg(
            signature,
            args,
            5,
            "scale",
            &["scale.left", "scale.right", "scale.none"],
        );

        for (index, arg) in args.iter().enumerate() {
            let is_precision = arg.name.as_deref() == Some("precision")
                || (arg.name.is_none()
                    && signature
                        .params
                        .get(index)
                        .is_some_and(|param| param.name == "precision"));
            if is_precision {
                if let Some(value) = self.known_const_int_for_validation(&arg.value)
                    && match value {
                        Ok(value) => !(0..=16).contains(&value),
                        Err(()) => true,
                    }
                {
                    self.diagnostics.push(Diagnostic::error(
                        "E_CALL_ARG_VALUE",
                        "`indicator` argument `precision` must be between 0 and 16",
                        arg.span,
                    ));
                }
                continue;
            }

            if self.validate_indicator_drawing_count_arg(signature, arg, index) {
                continue;
            }

            let is_max_bars_back = arg.name.as_deref() == Some("max_bars_back")
                || (arg.name.is_none()
                    && signature
                        .params
                        .get(index)
                        .is_some_and(|param| param.name == "max_bars_back"));
            if !is_max_bars_back {
                continue;
            }

            self.validate_max_bars_back_bound_value("indicator", "max_bars_back", arg);
        }
    }

    pub(crate) fn validate_max_bars_back_bound_value(
        &mut self,
        call_name: &str,
        arg_name: &str,
        arg: &CallArg,
    ) {
        let Some(value) = self.known_const_int_for_validation(&arg.value) else {
            return;
        };
        let message = if value.is_err() {
            Some(format!(
                "`{call_name}` argument `{arg_name}` must fit in a 32-bit unsigned history bound"
            ))
        } else if value.is_ok_and(|value| value < 0) {
            Some(format!(
                "`{call_name}` argument `{arg_name}` must be non-negative"
            ))
        } else if value.is_ok_and(|value| u32::try_from(value).is_err()) {
            Some(format!(
                "`{call_name}` argument `{arg_name}` must fit in a 32-bit unsigned history bound"
            ))
        } else {
            None
        };
        if let Some(message) = message {
            self.diagnostics
                .push(Diagnostic::error("E_CALL_ARG_VALUE", message, arg.span));
        }
    }

    pub(crate) fn validate_max_bars_back_args(
        &mut self,
        signature: &BuiltinSignature,
        args: &[CallArg],
    ) {
        if signature.name != "max_bars_back" {
            return;
        }

        for (index, arg) in args.iter().enumerate() {
            let is_num = is_call_arg(signature, arg, index, "num");
            if !is_num {
                continue;
            }

            self.validate_max_bars_back_bound_value("max_bars_back", "num", arg);
        }
    }
}

fn is_call_arg(signature: &BuiltinSignature, arg: &CallArg, index: usize, name: &str) -> bool {
    arg.name.as_deref() == Some(name)
        || (arg.name.is_none()
            && signature
                .params
                .get(index)
                .is_some_and(|param| param.name == name))
}
