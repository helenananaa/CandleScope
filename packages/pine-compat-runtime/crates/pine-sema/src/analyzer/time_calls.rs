use crate::prelude::*;

impl Analyzer {
    pub(crate) fn validate_time_function_args(
        &mut self,
        signature: &BuiltinSignature,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
    ) {
        if args.is_empty() {
            self.diagnostics.push(Diagnostic::error(
                "E_CALL_ARITY",
                format!("`{}` expects at least 1 argument(s), got 0", signature.name),
                Span::default(),
            ));
            return;
        }

        if args.len() > 5 {
            self.diagnostics.push(Diagnostic::error(
                "E_CALL_ARITY",
                format!(
                    "`{}` expects at most 5 argument(s), got {}",
                    signature.name,
                    args.len()
                ),
                args[5].span,
            ));
        }
        if !args.iter().enumerate().any(|(index, arg)| {
            arg.name.as_deref() == Some("timeframe") || (index == 0 && arg.name.is_none())
        }) {
            self.diagnostics.push(Diagnostic::error(
                "E_CALL_ARITY",
                format!("`{}` expects a `timeframe` argument", signature.name),
                args.first().map_or(Span::default(), |arg| arg.span),
            ));
        }

        for (index, arg) in args.iter().enumerate() {
            if let Some(name) = &arg.name {
                let accepts = match name.as_str() {
                    "timeframe" => Accepts::SimpleString,
                    "session" | "timezone" => Accepts::StringCompatible,
                    "bars_back" | "timeframe_bars_back" => Accepts::IntCompatible,
                    _ => {
                        self.diagnostics.push(Diagnostic::error(
                            "E_CALL_ARG_NAME",
                            format!("`{}` has no argument named `{name}`", signature.name),
                            arg.span,
                        ));
                        continue;
                    }
                };
                self.validate_time_function_arg_type(
                    signature.name,
                    name,
                    accepts,
                    index,
                    arg,
                    arg_types,
                );
                continue;
            }

            let Some((param_name, accepts)) =
                self.resolve_time_function_positional_arg(signature.name, args, arg_types, index)
            else {
                continue;
            };
            self.validate_time_function_arg_type(
                signature.name,
                param_name,
                accepts,
                index,
                arg,
                arg_types,
            );
        }
    }

    fn validate_time_function_arg_type(
        &mut self,
        function_name: &str,
        param_name: &str,
        accepts: Accepts,
        index: usize,
        arg: &CallArg,
        arg_types: &[Option<PineType>],
    ) {
        let Some(arg_type) = arg_types.get(index).copied().flatten() else {
            return;
        };
        if let Some(diagnostic) = call_arg_accepts_type_expected_diagnostic(
            function_name,
            param_name,
            accepts,
            arg_type,
            arg.span,
        ) {
            self.diagnostics.push(diagnostic);
        }
    }

    fn resolve_time_function_positional_arg(
        &mut self,
        function_name: &str,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
        index: usize,
    ) -> Option<(&'static str, Accepts)> {
        match index {
            0 => Some(("timeframe", Accepts::SimpleString)),
            1 => self.resolve_time_second_positional_arg(function_name, args, arg_types),
            2 => self.resolve_time_third_positional_arg(function_name, args, arg_types),
            3 => self.resolve_time_fourth_positional_arg(function_name, args, arg_types),
            4 => Some(("timeframe_bars_back", Accepts::IntCompatible)),
            _ => None,
        }
    }

    fn resolve_time_second_positional_arg(
        &mut self,
        function_name: &str,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
    ) -> Option<(&'static str, Accepts)> {
        let arg_type = arg_types.get(1).copied().flatten()?;
        if accepts_type(Accepts::IntCompatible, arg_type)
            && !accepts_type(Accepts::StringCompatible, arg_type)
        {
            return Some(("bars_back", Accepts::IntCompatible));
        }
        if accepts_type(Accepts::StringCompatible, arg_type) {
            return Some(("session", Accepts::StringCompatible));
        }
        self.diagnostics.push(call_arg_expected_type_diagnostic(
            function_name,
            "second positional",
            "a session string or bars_back int",
            arg_type,
            args[1].span,
        ));
        None
    }

    fn resolve_time_third_positional_arg(
        &mut self,
        function_name: &str,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
    ) -> Option<(&'static str, Accepts)> {
        let second_type = arg_types.get(1).copied().flatten()?;
        let third_type = arg_types.get(2).copied().flatten()?;
        if accepts_type(Accepts::IntCompatible, second_type)
            && !accepts_type(Accepts::StringCompatible, second_type)
        {
            return Some(("timeframe_bars_back", Accepts::IntCompatible));
        }
        if accepts_type(Accepts::StringCompatible, third_type) {
            return Some(("timezone", Accepts::StringCompatible));
        }
        if accepts_type(Accepts::IntCompatible, third_type) {
            return Some(("bars_back", Accepts::IntCompatible));
        }
        self.diagnostics.push(call_arg_expected_type_diagnostic(
            function_name,
            "third positional",
            "a timezone string or bars_back int",
            third_type,
            args[2].span,
        ));
        None
    }

    fn resolve_time_fourth_positional_arg(
        &mut self,
        function_name: &str,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
    ) -> Option<(&'static str, Accepts)> {
        let second_type = arg_types.get(1).copied().flatten()?;
        let third_type = arg_types.get(2).copied().flatten()?;
        if accepts_type(Accepts::IntCompatible, second_type)
            && !accepts_type(Accepts::StringCompatible, second_type)
        {
            self.diagnostics.push(Diagnostic::error(
                "E_CALL_ARITY",
                format!(
                    "`{}` positional bars_back overload expects at most 3 argument(s), got {}",
                    function_name,
                    args.len()
                ),
                args[3].span,
            ));
            return None;
        }
        if accepts_type(Accepts::StringCompatible, third_type) {
            return Some(("bars_back", Accepts::IntCompatible));
        }
        Some(("timeframe_bars_back", Accepts::IntCompatible))
    }

    pub(crate) fn validate_timestamp_args(
        &mut self,
        signature: &BuiltinSignature,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
    ) {
        if self.validate_timestamp_date_string_overload(signature.name, args, arg_types) {
            return;
        }

        let first_positional_is_timezone = args.first().is_some_and(|arg| arg.name.is_none())
            && arg_types
                .first()
                .copied()
                .flatten()
                .is_some_and(|arg_type| arg_type.kind == ValueKind::String);
        let has_timezone_arg = first_positional_is_timezone
            || args
                .iter()
                .any(|arg| arg.name.as_deref() == Some("timezone"));
        let max_args = if has_timezone_arg { 7 } else { 6 };
        if args.len() > max_args {
            self.diagnostics.push(Diagnostic::error(
                "E_CALL_ARITY",
                format!(
                    "`{}` expects at most {max_args} argument(s), got {}",
                    signature.name,
                    args.len()
                ),
                args[max_args].span,
            ));
        }

        let mut has_year = false;
        let mut has_month = false;
        let mut has_day = false;
        for (index, arg) in args.iter().enumerate() {
            let Some((param_name, accepts)) = self.resolve_timestamp_arg(
                signature.name,
                args,
                arg_types,
                index,
                first_positional_is_timezone,
            ) else {
                continue;
            };
            match param_name {
                "year" => has_year = true,
                "month" => has_month = true,
                "day" => has_day = true,
                _ => {}
            }
            self.validate_timestamp_arg_type(
                signature.name,
                param_name,
                accepts,
                index,
                arg,
                arg_types,
            );
        }

        if !has_year || !has_month || !has_day {
            self.diagnostics.push(Diagnostic::error(
                "E_CALL_ARITY",
                "`timestamp` expects year, month, and day arguments",
                args.first().map_or(Span::default(), |arg| arg.span),
            ));
        }
    }

    fn validate_timestamp_date_string_overload(
        &mut self,
        function_name: &str,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
    ) -> bool {
        let Some(first_arg) = args.first() else {
            return false;
        };
        let Some(first_type) = arg_types.first().copied().flatten() else {
            return false;
        };
        let is_date_string = if let Some(name) = first_arg.name.as_deref() {
            name == "dateString"
        } else {
            args.len() == 1 && first_type.kind == ValueKind::String
        };
        if !is_date_string {
            return false;
        }
        if args.len() > 1 {
            self.diagnostics.push(Diagnostic::error(
                "E_CALL_ARITY",
                format!("`{function_name}` dateString overload expects 1 argument"),
                args[1].span,
            ));
        }
        self.validate_timestamp_arg_type(
            function_name,
            "dateString",
            Accepts::ConstString,
            0,
            first_arg,
            arg_types,
        );
        true
    }

    fn validate_timestamp_arg_type(
        &mut self,
        function_name: &str,
        param_name: &str,
        accepts: Accepts,
        index: usize,
        arg: &CallArg,
        arg_types: &[Option<PineType>],
    ) {
        let Some(arg_type) = arg_types.get(index).copied().flatten() else {
            return;
        };
        if let Some(diagnostic) = call_arg_accepts_type_expected_diagnostic(
            function_name,
            param_name,
            accepts,
            arg_type,
            arg.span,
        ) {
            self.diagnostics.push(diagnostic);
        }
    }

    fn resolve_timestamp_arg(
        &mut self,
        function_name: &str,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
        index: usize,
        first_positional_is_timezone: bool,
    ) -> Option<(&'static str, Accepts)> {
        let arg = args.get(index)?;
        if let Some(name) = &arg.name {
            return match name.as_str() {
                "timezone" => Some(("timezone", Accepts::StringCompatible)),
                "year" => Some(("year", Accepts::IntCompatible)),
                "month" => Some(("month", Accepts::IntCompatible)),
                "day" => Some(("day", Accepts::IntCompatible)),
                "hour" => Some(("hour", Accepts::IntCompatible)),
                "minute" => Some(("minute", Accepts::IntCompatible)),
                "second" => Some(("second", Accepts::IntCompatible)),
                _ => {
                    self.diagnostics.push(Diagnostic::error(
                        "E_CALL_ARG_NAME",
                        format!("`{function_name}` has no argument named `{name}`"),
                        arg.span,
                    ));
                    None
                }
            };
        }

        if index == 0 && first_positional_is_timezone {
            return Some(("timezone", Accepts::StringCompatible));
        }
        if index == 0
            && arg_types
                .first()
                .copied()
                .flatten()
                .is_some_and(|arg_type| !accepts_type(Accepts::IntCompatible, arg_type))
        {
            if let Some(arg_type) = arg_types.first().copied().flatten() {
                self.diagnostics.push(call_arg_expected_type_diagnostic(
                    function_name,
                    "first positional",
                    "a year int or timezone string",
                    arg_type,
                    arg.span,
                ));
            }
            return None;
        }

        let calendar_index = if first_positional_is_timezone {
            index.checked_sub(1)?
        } else {
            index
        };
        Some((
            match calendar_index {
                0 => "year",
                1 => "month",
                2 => "day",
                3 => "hour",
                4 => "minute",
                5 => "second",
                _ => return None,
            },
            Accepts::IntCompatible,
        ))
    }
}
