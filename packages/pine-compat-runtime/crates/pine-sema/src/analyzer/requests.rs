use crate::prelude::*;

const REQUEST_SECURITY_UNSUPPORTED_REASON: &str = "only same-context request.security(syminfo.tickerid, timeframe.period, expression) scalar expressions, pure tuple literals, and selected tuple expressions, plus provider-backed same-or-higher-timeframe scalar expressions, pure tuple literals, and selected tuple expressions, are supported; optional gaps/lookahead are limited to barmerge.gaps_off and barmerge.lookahead_off, while lower-timeframe requests, provider local aliases, and side-effecting requested expressions are not implemented";
const REQUEST_SECURITY_LOWER_TF_UNSUPPORTED_REASON: &str = "array-returning lower-timeframe request semantics and host output shape for request.security_lower_tf are not designed in the supported request runtime";

impl Analyzer {
    pub(crate) fn analyze_request_call(
        &mut self,
        name: &str,
        span: Span,
        args: &[CallArg],
    ) -> Option<PineType> {
        match name {
            "request.security" => self.analyze_request_security(span, args),
            "request.security_lower_tf" => {
                self.unsupported(name, REQUEST_SECURITY_LOWER_TF_UNSUPPORTED_REASON, span);
                None
            }
            _ => {
                self.unsupported(
                    name,
                    "this request function is outside the supported request.security subset",
                    span,
                );
                None
            }
        }
    }

    fn analyze_request_security(&mut self, span: Span, args: &[CallArg]) -> Option<PineType> {
        let signature = pine_builtins::get_phase_1_builtin("request.security")?;
        self.compatibility.supported.push(FeatureUse {
            feature: "request.security".to_owned(),
            span,
        });

        let arg_types: Vec<_> = args
            .iter()
            .map(|arg| self.analyze_expr(&arg.value))
            .collect();
        self.validate_call_args(signature, args, &arg_types);

        let mut unsupported = false;
        if !(3..=5).contains(&args.len()) {
            unsupported = true;
        }
        if args.iter().take(3).any(|arg| arg.name.is_some()) {
            unsupported = true;
            self.diagnostics.push(Diagnostic::error(
                "E_CALL_ARG_NAME",
                "`request.security` currently requires symbol, timeframe, and expression as positional arguments",
                span,
            ));
        }
        if !self.validate_request_security_merge_args(args) {
            unsupported = true;
        }

        let same_context_symbol = args
            .first()
            .is_some_and(|arg| expr_name(&arg.value).as_deref() == Some("syminfo.tickerid"));
        let provider_symbol = args.first().is_some_and(|arg| {
            matches!(&arg.value.kind, ExprKind::Literal(Literal::String(value)) if !value.trim().is_empty())
        });
        if !same_context_symbol && !provider_symbol {
            unsupported = true;
        }
        let same_chart_timeframe = args
            .get(1)
            .is_some_and(|arg| expr_name(&arg.value).as_deref() == Some("timeframe.period"));
        let literal_timeframe = args.get(1).is_some_and(|arg| {
            matches!(&arg.value.kind, ExprKind::Literal(Literal::String(value)) if !value.trim().is_empty())
        });
        if !same_chart_timeframe && !literal_timeframe {
            unsupported = true;
        }

        let expression_type = arg_types.get(2).copied().flatten();
        let same_context_request = same_context_symbol && same_chart_timeframe;
        if expression_type.is_none_or(|pine_type| {
            if same_context_request {
                !is_request_same_context_type(pine_type)
            } else {
                !is_request_provider_type(pine_type)
            }
        }) {
            unsupported = true;
        }
        let supported_expression = args.get(2).is_some_and(|arg| {
            if same_context_request {
                request_expression_is_same_context_value(&arg.value)
            } else if expression_type.is_some_and(|pine_type| pine_type.kind == ValueKind::Tuple) {
                request_expression_is_provider_tuple_value(&arg.value)
            } else if provider_symbol || literal_timeframe {
                request_expression_is_provider_scalar(&arg.value)
            } else {
                false
            }
        });
        if !supported_expression {
            unsupported = true;
        }
        if unsupported {
            self.unsupported(
                "request.security",
                REQUEST_SECURITY_UNSUPPORTED_REASON,
                span,
            );
            return expression_type.map(series_request_type);
        }

        expression_type.map(series_request_type)
    }

    fn validate_request_security_merge_args(&mut self, args: &[CallArg]) -> bool {
        let mut supported = true;
        let signature = pine_builtins::get_phase_1_builtin("request.security")
            .expect("request.security signature must exist");
        self.validate_label_string_arg(signature, args, 3, "gaps", &["barmerge.gaps_off"]);
        self.validate_label_string_arg(
            signature,
            args,
            4,
            "lookahead",
            &["barmerge.lookahead_off"],
        );

        for (index, arg) in args.iter().enumerate().skip(3) {
            let allowed_name = match arg.name.as_deref() {
                Some("gaps") => "gaps",
                Some("lookahead") => "lookahead",
                Some(_) => {
                    supported = false;
                    continue;
                }
                None => match index {
                    3 => "gaps",
                    4 => "lookahead",
                    _ => {
                        supported = false;
                        continue;
                    }
                },
            };
            let Some(value) = self.known_const_string_value(&arg.value) else {
                continue;
            };
            let allowed_value = if allowed_name == "gaps" {
                "barmerge.gaps_off"
            } else {
                "barmerge.lookahead_off"
            };
            if value != allowed_value {
                supported = false;
            }
        }
        supported
    }
}

fn series_request_type(pine_type: PineType) -> PineType {
    PineType::new(Qualifier::Series, pine_type.kind)
}

fn is_request_scalar_type(pine_type: PineType) -> bool {
    matches!(
        pine_type.kind,
        ValueKind::Int
            | ValueKind::Float
            | ValueKind::Bool
            | ValueKind::String
            | ValueKind::Color
            | ValueKind::Na
    )
}

fn is_request_same_context_type(pine_type: PineType) -> bool {
    is_request_scalar_type(pine_type) || pine_type.kind == ValueKind::Tuple
}

fn is_request_provider_type(pine_type: PineType) -> bool {
    is_request_scalar_type(pine_type) || pine_type.kind == ValueKind::Tuple
}

fn request_expression_is_same_context_value(expr: &Expr) -> bool {
    match &expr.kind {
        ExprKind::Tuple(items) => items.iter().all(request_expression_is_same_context_value),
        _ => request_expression_is_pure_scalar(expr),
    }
}

fn request_expression_is_pure_scalar(expr: &Expr) -> bool {
    match &expr.kind {
        ExprKind::Literal(_) | ExprKind::Identifier(_) => true,
        ExprKind::QualifiedName(_) => expr_name(expr)
            .as_deref()
            .is_none_or(|name| !is_strategy_state_variable(name)),
        ExprKind::Unary { expr, .. } => request_expression_is_pure_scalar(expr),
        ExprKind::Binary { left, right, .. } => {
            request_expression_is_pure_scalar(left) && request_expression_is_pure_scalar(right)
        }
        ExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => {
            request_expression_is_pure_scalar(condition)
                && request_expression_is_pure_scalar(then_expr)
                && request_expression_is_pure_scalar(else_expr)
        }
        ExprKind::History { expr, offset } => {
            request_expression_is_pure_scalar(expr) && request_expression_is_pure_scalar(offset)
        }
        ExprKind::Call { callee, args } => {
            let Some(name) = expr_name(callee) else {
                return false;
            };
            (request_scalar_call_is_supported(name.as_str())
                || request_tuple_call_is_supported(name.as_str()))
                && args.iter().all(|arg| {
                    arg.name.is_none() && request_expression_is_same_context_value(&arg.value)
                })
        }
        ExprKind::Switch { selector, arms } => {
            selector
                .as_deref()
                .is_none_or(request_expression_is_same_context_value)
                && arms.iter().all(|arm| {
                    arm.condition
                        .as_ref()
                        .is_none_or(request_expression_is_same_context_value)
                        && match &arm.result {
                            SwitchArmResult::Expr(result) => {
                                request_expression_is_same_context_value(result)
                            }
                            SwitchArmResult::Block(_) => false,
                        }
                })
        }
        ExprKind::Tuple(_)
        | ExprKind::If { .. }
        | ExprKind::For { .. }
        | ExprKind::ForIn { .. }
        | ExprKind::While { .. } => false,
    }
}

fn request_tuple_call_is_supported(name: &str) -> bool {
    matches!(
        name,
        "ta.macd" | "ta.bb" | "ta.kc" | "ta.supertrend" | "ta.dmi" | "ta.vwap"
    )
}

fn request_expression_is_provider_tuple_value(expr: &Expr) -> bool {
    match &expr.kind {
        ExprKind::Tuple(items) => items.iter().all(request_expression_is_provider_scalar),
        ExprKind::Call { callee, args } => {
            let Some(name) = expr_name(callee) else {
                return false;
            };
            request_provider_tuple_call_is_supported(name.as_str())
                && args.iter().all(|arg| {
                    arg.name.is_none() && request_expression_is_provider_scalar(&arg.value)
                })
        }
        _ => false,
    }
}

fn request_provider_tuple_call_is_supported(name: &str) -> bool {
    matches!(
        name,
        "ta.macd" | "ta.bb" | "ta.kc" | "ta.supertrend" | "ta.dmi" | "ta.vwap"
    )
}

fn request_expression_is_provider_scalar(expr: &Expr) -> bool {
    match &expr.kind {
        ExprKind::Literal(_) => true,
        ExprKind::Identifier(_) | ExprKind::QualifiedName(_) => expr_name(expr)
            .as_deref()
            .is_some_and(is_request_provider_scalar_name),
        ExprKind::Unary { expr, .. } => request_expression_is_provider_scalar(expr),
        ExprKind::Binary { left, right, .. } => {
            request_expression_is_provider_scalar(left)
                && request_expression_is_provider_scalar(right)
        }
        ExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => {
            request_expression_is_provider_scalar(condition)
                && request_expression_is_provider_scalar(then_expr)
                && request_expression_is_provider_scalar(else_expr)
        }
        ExprKind::History { expr, offset } => {
            request_expression_is_provider_scalar(expr)
                && request_expression_is_provider_scalar(offset)
        }
        ExprKind::Call { callee, args } => {
            let Some(name) = expr_name(callee) else {
                return false;
            };
            request_scalar_call_is_supported(name.as_str())
                && args.iter().all(|arg| {
                    arg.name.is_none() && request_expression_is_provider_scalar(&arg.value)
                })
        }
        ExprKind::Switch { selector, arms } => {
            selector
                .as_deref()
                .is_none_or(request_expression_is_provider_scalar)
                && arms.iter().all(|arm| {
                    arm.condition
                        .as_ref()
                        .is_none_or(request_expression_is_provider_scalar)
                        && match &arm.result {
                            SwitchArmResult::Expr(result) => {
                                request_expression_is_provider_scalar(result)
                            }
                            SwitchArmResult::Block(_) => false,
                        }
                })
        }
        ExprKind::Tuple(_)
        | ExprKind::If { .. }
        | ExprKind::For { .. }
        | ExprKind::ForIn { .. }
        | ExprKind::While { .. } => false,
    }
}

fn is_request_provider_scalar_name(name: &str) -> bool {
    matches!(
        name,
        "open"
            | "high"
            | "low"
            | "close"
            | "volume"
            | "time"
            | "ta.accdist"
            | "ta.iii"
            | "ta.nvi"
            | "ta.obv"
            | "ta.pvi"
            | "ta.pvt"
            | "ta.wvad"
    )
}

fn request_scalar_call_is_supported(name: &str) -> bool {
    matches!(
        name,
        "na" | "nz"
            | "math.abs"
            | "math.max"
            | "math.min"
            | "math.avg"
            | "math.floor"
            | "math.ceil"
            | "math.trunc"
            | "math.sqrt"
            | "math.cbrt"
            | "math.log"
            | "math.log10"
            | "math.exp"
            | "math.acos"
            | "math.asin"
            | "math.atan"
            | "math.sign"
            | "math.todegrees"
            | "math.toradians"
            | "math.sin"
            | "math.cos"
            | "math.tan"
            | "math.pow"
            | "math.hypot"
            | "math.round"
            | "math.round_to_mintick"
            | "math.sum"
            | "ta.cum"
            | "ta.sma"
            | "ta.ema"
            | "ta.dema"
            | "ta.tema"
            | "ta.rma"
            | "ta.rsi"
            | "ta.tsi"
            | "ta.cmo"
            | "ta.cci"
            | "ta.cog"
            | "ta.bop"
            | "ta.ao"
            | "ta.max"
            | "ta.min"
            | "ta.mfi"
            | "ta.stoch"
            | "ta.wpr"
            | "ta.sar"
            | "ta.tr"
            | "ta.atr"
            | "ta.highest"
            | "ta.lowest"
            | "ta.highestbars"
            | "ta.lowestbars"
            | "ta.change"
            | "ta.mom"
            | "ta.roc"
            | "ta.range"
            | "ta.dev"
            | "ta.vwap"
            | "ta.bbw"
            | "ta.kcw"
            | "ta.pivothigh"
            | "ta.pivotlow"
            | "ta.correlation"
            | "ta.covariance"
            | "ta.median"
            | "ta.mode"
            | "ta.percentile_linear_interpolation"
            | "ta.percentile_nearest_rank"
            | "ta.percentrank"
            | "ta.stdev"
            | "ta.variance"
            | "ta.wma"
            | "ta.vwma"
            | "ta.swma"
            | "ta.hma"
            | "ta.alma"
            | "ta.linreg"
            | "ta.rising"
            | "ta.falling"
            | "ta.barssince"
            | "ta.valuewhen"
            | "ta.cross"
            | "ta.crossover"
            | "ta.crossunder"
    )
}
