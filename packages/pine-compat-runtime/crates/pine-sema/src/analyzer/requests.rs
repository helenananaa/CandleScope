use crate::prelude::*;

const REQUEST_SECURITY_UNSUPPORTED_REASON: &str = "only same-context request.security(syminfo.tickerid, timeframe.period, expression) scalar expressions, pure tuple literals, and selected tuple expressions, plus provider-backed same-or-higher-timeframe scalar expressions, pure tuple literals, and selected tuple expressions, are supported; optional gaps/lookahead are limited to barmerge.gaps_off and barmerge.lookahead_off, while lower-timeframe requests, provider local aliases, and side-effecting requested expressions are not implemented";
const LEGACY_SECURITY_UNSUPPORTED_REASON: &str = "legacy security supports same-context or host-provided same-or-higher-timeframe requests whose expression is in the request.security scalar/tuple subset; lower-timeframe requests, local aliases, UDF calls, mutable captures, and side effects remain unsupported";
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
        self.compatibility.supported.push(FeatureUse {
            feature: "request.security".to_owned(),
            span,
        });

        let arg_types: Vec<_> = args
            .iter()
            .map(|arg| self.analyze_expr(&arg.value))
            .collect();
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

        self.analyze_request_security_core(
            span,
            args,
            &arg_types,
            false,
            unsupported,
            REQUEST_SECURITY_UNSUPPORTED_REASON,
        )
    }

    pub(crate) fn analyze_bound_legacy_security(
        &mut self,
        span: Span,
        bound: &crate::legacy::BoundLegacySecurity,
    ) -> Option<PineType> {
        self.compatibility.supported.push(FeatureUse {
            feature: "security".to_owned(),
            span,
        });
        self.analyze_request_security_core(
            span,
            &bound.canonical_args,
            &bound.canonical_arg_types,
            true,
            false,
            LEGACY_SECURITY_UNSUPPORTED_REASON,
        )
    }

    fn analyze_request_security_core(
        &mut self,
        span: Span,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
        legacy: bool,
        mut unsupported: bool,
        unsupported_reason: &str,
    ) -> Option<PineType> {
        let signature = pine_builtins::get_phase_1_builtin("request.security")
            .expect("request.security signature must exist");
        self.validate_call_args(signature, args, arg_types);

        let same_context_symbol = args
            .first()
            .is_some_and(|arg| self.request_symbol_is_chart(&arg.value, legacy));
        let provider_symbol = args.first().is_some_and(|arg| {
            matches!(&arg.value.kind, ExprKind::Literal(Literal::String(value)) if !value.trim().is_empty())
        });
        if !same_context_symbol && !provider_symbol {
            unsupported = true;
        }
        let same_chart_timeframe = args
            .get(1)
            .is_some_and(|arg| self.request_timeframe_is_chart(&arg.value, legacy));
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
                self.request_expression_is_same_context_value(&arg.value)
            } else if expression_type.is_some_and(|pine_type| pine_type.kind == ValueKind::Tuple) {
                self.request_expression_is_provider_tuple_value(&arg.value)
            } else if provider_symbol || literal_timeframe {
                self.request_expression_is_provider_scalar(&arg.value)
            } else {
                false
            }
        });
        if !supported_expression {
            unsupported = true;
        }
        if unsupported {
            self.unsupported(
                if legacy {
                    "security"
                } else {
                    "request.security"
                },
                unsupported_reason,
                span,
            );
            return expression_type.map(series_request_type);
        }

        expression_type.map(series_request_type)
    }

    fn request_symbol_is_chart(&self, expr: &Expr, legacy: bool) -> bool {
        expr_name(expr)
            .as_deref()
            .is_some_and(|name| name == "syminfo.tickerid" || (legacy && name == "tickerid"))
    }

    fn request_timeframe_is_chart(&self, expr: &Expr, legacy: bool) -> bool {
        expr_name(expr)
            .as_deref()
            .is_some_and(|name| name == "timeframe.period" || (legacy && name == "period"))
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

    fn request_expression_is_same_context_value(&self, expr: &Expr) -> bool {
        match &expr.kind {
            ExprKind::Tuple(items) => items
                .iter()
                .all(|item| self.request_expression_is_same_context_value(item)),
            _ => self.request_expression_is_pure_scalar(expr),
        }
    }

    fn request_expression_is_pure_scalar(&self, expr: &Expr) -> bool {
        match &expr.kind {
            ExprKind::Literal(_) | ExprKind::Identifier(_) => true,
            ExprKind::QualifiedName(_) => expr_name(expr)
                .as_deref()
                .is_none_or(|name| !is_strategy_state_variable(name)),
            ExprKind::Unary { expr, .. } => self.request_expression_is_pure_scalar(expr),
            ExprKind::Binary { left, right, .. } => {
                self.request_expression_is_pure_scalar(left)
                    && self.request_expression_is_pure_scalar(right)
            }
            ExprKind::Ternary {
                condition,
                then_expr,
                else_expr,
            } => {
                self.request_expression_is_pure_scalar(condition)
                    && self.request_expression_is_pure_scalar(then_expr)
                    && self.request_expression_is_pure_scalar(else_expr)
            }
            ExprKind::History { expr, offset } => {
                self.request_expression_is_pure_scalar(expr)
                    && self.request_expression_is_pure_scalar(offset)
            }
            ExprKind::Call { callee, args } => {
                let Some(name) = self.request_expression_call_name(callee) else {
                    return false;
                };
                (request_scalar_call_is_supported(&name) || request_tuple_call_is_supported(&name))
                    && args.iter().all(|arg| {
                        arg.name.is_none()
                            && self.request_expression_is_same_context_value(&arg.value)
                    })
            }
            ExprKind::Switch { selector, arms } => {
                selector
                    .as_deref()
                    .is_none_or(|selector| self.request_expression_is_same_context_value(selector))
                    && arms.iter().all(|arm| {
                        arm.condition.as_ref().is_none_or(|condition| {
                            self.request_expression_is_same_context_value(condition)
                        }) && match &arm.result {
                            SwitchArmResult::Expr(result) => {
                                self.request_expression_is_same_context_value(result)
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

    fn request_expression_is_provider_tuple_value(&self, expr: &Expr) -> bool {
        match &expr.kind {
            ExprKind::Tuple(items) => items
                .iter()
                .all(|item| self.request_expression_is_provider_scalar(item)),
            ExprKind::Call { callee, args } => {
                let Some(name) = self.request_expression_call_name(callee) else {
                    return false;
                };
                request_provider_tuple_call_is_supported(&name)
                    && args.iter().all(|arg| {
                        arg.name.is_none() && self.request_expression_is_provider_scalar(&arg.value)
                    })
            }
            _ => false,
        }
    }

    fn request_expression_is_provider_scalar(&self, expr: &Expr) -> bool {
        match &expr.kind {
            ExprKind::Literal(_) => true,
            ExprKind::Identifier(_) | ExprKind::QualifiedName(_) => expr_name(expr)
                .as_deref()
                .is_some_and(is_request_provider_scalar_name),
            ExprKind::Unary { expr, .. } => self.request_expression_is_provider_scalar(expr),
            ExprKind::Binary { left, right, .. } => {
                self.request_expression_is_provider_scalar(left)
                    && self.request_expression_is_provider_scalar(right)
            }
            ExprKind::Ternary {
                condition,
                then_expr,
                else_expr,
            } => {
                self.request_expression_is_provider_scalar(condition)
                    && self.request_expression_is_provider_scalar(then_expr)
                    && self.request_expression_is_provider_scalar(else_expr)
            }
            ExprKind::History { expr, offset } => {
                self.request_expression_is_provider_scalar(expr)
                    && self.request_expression_is_provider_scalar(offset)
            }
            ExprKind::Call { callee, args } => {
                let Some(name) = self.request_expression_call_name(callee) else {
                    return false;
                };
                request_scalar_call_is_supported(&name)
                    && args.iter().all(|arg| {
                        arg.name.is_none() && self.request_expression_is_provider_scalar(&arg.value)
                    })
            }
            ExprKind::Switch { selector, arms } => {
                selector
                    .as_deref()
                    .is_none_or(|selector| self.request_expression_is_provider_scalar(selector))
                    && arms.iter().all(|arm| {
                        arm.condition.as_ref().is_none_or(|condition| {
                            self.request_expression_is_provider_scalar(condition)
                        }) && match &arm.result {
                            SwitchArmResult::Expr(result) => {
                                self.request_expression_is_provider_scalar(result)
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

    fn request_expression_call_name(&self, callee: &Expr) -> Option<String> {
        let name = expr_name(callee)?;
        Some(
            self.legacy
                .canonical_call_name(self.current_source_context_id(), callee.span)
                .map_or(name, str::to_owned),
        )
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

fn request_tuple_call_is_supported(name: &str) -> bool {
    matches!(
        name,
        "ta.macd" | "ta.bb" | "ta.kc" | "ta.supertrend" | "ta.dmi" | "ta.vwap"
    )
}

fn request_provider_tuple_call_is_supported(name: &str) -> bool {
    matches!(
        name,
        "ta.macd" | "ta.bb" | "ta.kc" | "ta.supertrend" | "ta.dmi" | "ta.vwap"
    )
}

fn is_request_provider_scalar_name(name: &str) -> bool {
    matches!(
        name,
        "syminfo.tickerid"
            | "timeframe.period"
            | "open"
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
