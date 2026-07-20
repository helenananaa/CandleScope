use crate::prelude::*;

impl Analyzer {
    pub(super) fn lower_legacy_value(&self, span: Span) -> Option<HirExprKind> {
        if let Some(value) = self
            .legacy
            .canonical_string_value(self.current_source_context_id(), span)
        {
            return Some(HirExprKind::Literal(HirLiteral::String(value.to_owned())));
        }
        self.legacy
            .canonical_value_name(self.current_source_context_id(), span)
            .map(|canonical_name| {
                self.scope.resolve(canonical_name).map_or_else(
                    || HirExprKind::Builtin(canonical_name.to_owned()),
                    |symbol| HirExprKind::Symbol(symbol.id),
                )
            })
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) fn lower_recorded_legacy_call(
        &mut self,
        span: Span,
        args: &[CallArg],
        pine_type: PineType,
        series_id: Option<pine_ir::SeriesId>,
        param_exprs: &HashMap<String, HirExpr>,
        param_types: &HashMap<String, PineType>,
    ) -> Option<Option<HirExpr>> {
        let lowering = self
            .legacy
            .call_lowering(self.current_source_context_id(), span)?;
        Some(match lowering {
            crate::legacy::LegacyCallLowering::HistoryOffset => self.lower_legacy_history_offset(
                span,
                args,
                pine_type,
                series_id,
                param_exprs,
                param_types,
            ),
            crate::legacy::LegacyCallLowering::SecuritySpan { start, end } => self
                .lower_legacy_security_call(
                    span,
                    args,
                    pine_type,
                    series_id,
                    start,
                    end,
                    param_exprs,
                    param_types,
                ),
        })
    }

    pub(super) fn lower_legacy_call_args(
        &self,
        span: Span,
        args: &[CallArg],
    ) -> Option<Vec<CallArg>> {
        self.legacy
            .canonical_call_arg_rewrites(self.current_source_context_id(), span)
            .map(|rewrites| {
                args.iter()
                    .zip(rewrites)
                    .filter_map(|(arg, rewrite)| {
                        if !rewrite.keep {
                            return None;
                        }
                        let mut arg = arg.clone();
                        arg.name = rewrite.canonical_name.map(str::to_owned);
                        Some(arg)
                    })
                    .collect()
            })
    }

    pub(super) fn lower_legacy_history_offset(
        &mut self,
        span: Span,
        args: &[CallArg],
        pine_type: PineType,
        series_id: Option<pine_ir::SeriesId>,
        param_exprs: &HashMap<String, HirExpr>,
        param_types: &HashMap<String, PineType>,
    ) -> Option<HirExpr> {
        let canonical_args = self
            .lower_legacy_call_args(span, args)
            .expect("focused legacy history lowering records argument roles");
        let source = canonical_args
            .iter()
            .find(|arg| arg.name.as_deref() == Some("source"))
            .expect("validated legacy offset source");
        let offset_arg = canonical_args
            .iter()
            .find(|arg| arg.name.as_deref() == Some("offset"))
            .expect("validated legacy offset amount");
        let offset = match self
            .known_history_offset_int_value(&offset_arg.value)
            .and_then(|value| u32::try_from(value).ok())
        {
            Some(offset) => HirHistoryOffset::Constant(offset),
            None => HirHistoryOffset::Dynamic(Box::new(self.lower_expr_with_params(
                &offset_arg.value,
                param_exprs,
                param_types,
            )?)),
        };
        let mut lowered_source =
            self.lower_expr_with_params(&source.value, param_exprs, param_types)?;
        if lowered_source.series_id.is_none() {
            lowered_source.series_id = self.lower_expr_series_id(
                &source.value,
                PineType::new(Qualifier::Series, lowered_source.pine_type.kind),
            );
        }
        Some(HirExpr {
            pine_type,
            series_id,
            kind: HirExprKind::History {
                expr: Box::new(lowered_source),
                offset,
            },
        })
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) fn lower_legacy_security_call(
        &mut self,
        span: Span,
        args: &[CallArg],
        pine_type: PineType,
        series_id: Option<pine_ir::SeriesId>,
        source_span_start: usize,
        source_span_end: usize,
        param_exprs: &HashMap<String, HirExpr>,
        param_types: &HashMap<String, PineType>,
    ) -> Option<HirExpr> {
        let callee = self
            .legacy
            .canonical_call_name(self.current_source_context_id(), span)?
            .to_owned();
        let canonical_args = self.lower_legacy_call_args(span, args)?;
        let mut lowered_args =
            self.lower_builtin_call_args(&callee, &canonical_args, param_exprs, param_types)?;
        lowered_args.push(HirCallArg {
            name: Some("$legacy_span_start".to_owned()),
            value: HirExpr {
                kind: HirExprKind::Literal(HirLiteral::Int(
                    i64::try_from(source_span_start).unwrap_or(i64::MAX),
                )),
                pine_type: PineType::new(Qualifier::Const, ValueKind::Int),
                series_id: None,
            },
        });
        lowered_args.push(HirCallArg {
            name: Some("$legacy_span_end".to_owned()),
            value: HirExpr {
                kind: HirExprKind::Literal(HirLiteral::Int(
                    i64::try_from(source_span_end).unwrap_or(i64::MAX),
                )),
                pine_type: PineType::new(Qualifier::Const, ValueKind::Int),
                series_id: None,
            },
        });
        Some(HirExpr {
            pine_type,
            series_id,
            kind: HirExprKind::Call {
                callee,
                call_site_id: self.alloc_call_site(),
                args: lowered_args,
            },
        })
    }
}
