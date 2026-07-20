use crate::prelude::*;

#[derive(Default)]
struct LegacyInputTrace {
    symbols: std::collections::HashSet<SymbolId>,
    functions: std::collections::HashSet<String>,
}

pub(super) enum FocusedLegacyCallAnalysis {
    NotApplicable,
    Analyzed(Option<PineType>),
}

impl Analyzer {
    pub(super) fn reject_legacy_builtin_method_syntax(
        &mut self,
        receiver: &str,
        method: &str,
        span: Span,
    ) -> bool {
        if self.legacy.dialect().version() >= 5 {
            return false;
        }
        self.reject_unavailable_legacy_builtin(&format!("{receiver}.{method}"), 5, span);
        true
    }

    pub(super) fn reject_legacy_named_call_args(
        &mut self,
        name: &str,
        args: &[CallArg],
        callee_span: Span,
    ) -> bool {
        let dialect = self.legacy.dialect();
        let is_pre_v3 = matches!(dialect, crate::PineDialect::V1 | crate::PineDialect::V2);
        let is_udf = self.functions.contains_key(name);
        let rejects_legacy_udf_keywords = dialect.is_legacy() && is_udf;
        if !is_pre_v3 && !rejects_legacy_udf_keywords {
            return false;
        }
        let Some(named_arg) = args.iter().find(|arg| arg.name.is_some()) else {
            return false;
        };
        if rejects_legacy_udf_keywords {
            self.diagnostics.push(Diagnostic::error(
                "E_CALL_ARG_NAME",
                format!(
                    "named arguments are not supported by Pine {} user-defined function `{name}`; legacy user-defined function calls require positional arguments",
                    dialect.name(),
                ),
                named_arg.span.merge(callee_span),
            ));
            return true;
        }

        let resolution = self.legacy.resolve_call(name);
        let is_symbol_shadowed = self
            .bound_symbol(name, callee_span)
            .or_else(|| self.scope.resolve(name))
            .is_some();
        let is_annotation = !is_symbol_shadowed
            && (name == "alertcondition"
                || matches!(
                    resolution,
                    Some(
                        crate::legacy::LegacyResolution::Focused(crate::legacy::LegacyRule {
                            kind: crate::legacy::LegacyRuleKind::FocusedDeclaration
                                | crate::legacy::LegacyRuleKind::FocusedInput
                                | crate::legacy::LegacyRuleKind::FocusedOutput,
                            ..
                        }) | crate::legacy::LegacyResolution::UnsupportedKnown(
                            crate::legacy::LegacyRule {
                                kind: crate::legacy::LegacyRuleKind::FocusedOutput,
                                ..
                            }
                        )
                    )
                ));
        let is_builtin = !is_symbol_shadowed
            && (resolution.is_some() || pine_builtins::is_phase_1_builtin(name));
        if !is_builtin || is_annotation {
            return false;
        }

        self.diagnostics.push(Diagnostic::error(
            "E_CALL_ARG_NAME",
            format!(
                "named arguments are not supported by Pine {} ordinary built-in `{name}`; before Pine v3 they are limited to annotation calls",
                dialect.name(),
            ),
            named_arg.span.merge(callee_span),
        ));
        true
    }

    pub(super) fn reject_legacy_input_constant_leaks(
        &mut self,
        name: &str,
        callee: &Expr,
        args: &[CallArg],
    ) -> bool {
        let allowed_type_span = self
            .is_unshadowed_focused_legacy_input_call(name, callee)
            .then(|| self.legacy.explicit_legacy_input_type_expr(args))
            .flatten()
            .map(|expr| expr.span);

        for arg in args {
            let is_exact_selector = self.legacy_input_type_marker(&arg.value).is_some();
            let is_allowed_selector =
                is_exact_selector && allowed_type_span == Some(arg.value.span);
            if self.legacy_input_constant_in_expr(&arg.value) && !is_allowed_selector {
                self.report_legacy_input_constant_context(
                    "legacy input type constants are only valid as the `type` selector of the versioned `input` annotation",
                    arg.value.span,
                );
                return true;
            }
        }
        false
    }

    pub(crate) fn reject_legacy_input_constant_reassignment(&mut self, value: &Expr) -> bool {
        self.reject_legacy_input_constant_semantic_use(
            value,
            "legacy input type constants cannot be reassigned; keep an exact const alias for the `type` selector of the versioned `input` annotation",
        )
    }

    pub(crate) fn reject_legacy_input_constant_symbol_reassignment(
        &mut self,
        name: &str,
        value: &Expr,
        span: Span,
    ) -> bool {
        let target_contains_marker = self.scope.resolve(name).is_some_and(|symbol| {
            self.symbol_init_exprs
                .get(&symbol.id)
                .cloned()
                .is_some_and(|initializer| {
                    self.with_source_context_ref(initializer.source_context_id, |analyzer| {
                        analyzer.legacy_input_constant_in_expr(&initializer.expr)
                    })
                })
        });
        if !target_contains_marker && !self.legacy_input_constant_in_expr(value) {
            return false;
        }
        self.report_legacy_input_constant_context(
            "legacy input type constant aliases cannot be reassigned; keep an exact const alias for the `type` selector of the versioned `input` annotation",
            span,
        );
        true
    }

    pub(crate) fn reject_legacy_input_constant_declaration(&mut self, value: &Expr) -> bool {
        if self.legacy_input_type_marker(value).is_some() {
            return false;
        }
        self.reject_legacy_input_constant_semantic_use(
            value,
            "legacy input type constants may only be preserved as an exact const alias for the `type` selector of the versioned `input` annotation",
        )
    }

    pub(crate) fn reject_legacy_input_constant_expression(&mut self, expr: &Expr) -> bool {
        self.reject_legacy_input_constant_semantic_use(
            expr,
            "legacy input type constants cannot be used as ordinary expression values; they are only valid as the `type` selector of the versioned `input` annotation",
        )
    }

    fn reject_legacy_input_constant_semantic_use(
        &mut self,
        expr: &Expr,
        message: &'static str,
    ) -> bool {
        if !self.legacy_input_constant_in_expr(expr) {
            return false;
        }
        self.report_legacy_input_constant_context(message, expr.span);
        true
    }

    fn report_legacy_input_constant_context(&mut self, message: &'static str, span: Span) {
        if self
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_LEGACY_INPUT_CONSTANT_CONTEXT")
        {
            return;
        }
        self.diagnostics.push(Diagnostic::error(
            "E_LEGACY_INPUT_CONSTANT_CONTEXT",
            message,
            span,
        ));
    }

    fn legacy_input_constant_in_expr(&self, expr: &Expr) -> bool {
        self.legacy_input_constant_in_expr_inner(expr, &mut LegacyInputTrace::default())
    }

    fn legacy_input_constant_in_expr_inner(
        &self,
        expr: &Expr,
        trace: &mut LegacyInputTrace,
    ) -> bool {
        if self.legacy_input_type_marker_inner(expr, trace).is_some() {
            return true;
        }
        match &expr.kind {
            ExprKind::Unary { expr, .. } => self.legacy_input_constant_in_expr_inner(expr, trace),
            ExprKind::Binary { left, right, .. } => {
                self.legacy_input_constant_in_expr_inner(left, trace)
                    || self.legacy_input_constant_in_expr_inner(right, trace)
            }
            ExprKind::Ternary {
                condition,
                then_expr,
                else_expr,
            } => {
                self.legacy_input_constant_in_expr_inner(condition, trace)
                    || self.legacy_input_constant_in_expr_inner(then_expr, trace)
                    || self.legacy_input_constant_in_expr_inner(else_expr, trace)
            }
            ExprKind::If {
                condition,
                then_branch,
                else_branch,
            } => {
                self.legacy_input_constant_in_expr_inner(condition, trace)
                    || self.legacy_input_constant_in_statements(then_branch, trace)
                    || self.legacy_input_constant_in_statements(else_branch, trace)
            }
            ExprKind::For {
                from,
                to,
                step,
                body,
                ..
            } => {
                self.legacy_input_constant_in_expr_inner(from, trace)
                    || self.legacy_input_constant_in_expr_inner(to, trace)
                    || step
                        .as_deref()
                        .is_some_and(|step| self.legacy_input_constant_in_expr_inner(step, trace))
                    || self.legacy_input_constant_in_statements(body, trace)
            }
            ExprKind::ForIn { iterable, body, .. } => {
                self.legacy_input_constant_in_expr_inner(iterable, trace)
                    || self.legacy_input_constant_in_statements(body, trace)
            }
            ExprKind::While { condition, body } => {
                self.legacy_input_constant_in_expr_inner(condition, trace)
                    || self.legacy_input_constant_in_statements(body, trace)
            }
            ExprKind::Switch { selector, arms } => {
                selector.as_deref().is_some_and(|selector| {
                    self.legacy_input_constant_in_expr_inner(selector, trace)
                }) || arms.iter().any(|arm| {
                    arm.condition.as_ref().is_some_and(|condition| {
                        self.legacy_input_constant_in_expr_inner(condition, trace)
                    }) || match &arm.result {
                        SwitchArmResult::Expr(result) => {
                            self.legacy_input_constant_in_expr_inner(result, trace)
                        }
                        SwitchArmResult::Block(statements) => {
                            self.legacy_input_constant_in_statements(statements, trace)
                        }
                    }
                })
            }
            ExprKind::Tuple(items) => items
                .iter()
                .any(|item| self.legacy_input_constant_in_expr_inner(item, trace)),
            ExprKind::Call { callee, .. } => {
                self.legacy_input_constant_in_call_result(callee, trace)
            }
            ExprKind::History { expr, offset } => {
                self.legacy_input_constant_in_expr_inner(expr, trace)
                    || self.legacy_input_constant_in_expr_inner(offset, trace)
            }
            ExprKind::Identifier(name) => {
                let Some(symbol) = self
                    .bound_symbol(name, expr.span)
                    .or_else(|| self.scope.resolve(name))
                else {
                    return false;
                };
                if !trace.symbols.insert(symbol.id) {
                    return false;
                }
                let contains =
                    self.symbol_init_exprs
                        .get(&symbol.id)
                        .cloned()
                        .is_some_and(|initializer| {
                            self.with_source_context_ref(
                                initializer.source_context_id,
                                |analyzer| {
                                    analyzer.legacy_input_constant_in_expr_inner(
                                        &initializer.expr,
                                        trace,
                                    )
                                },
                            )
                        });
                trace.symbols.remove(&symbol.id);
                contains
            }
            ExprKind::Literal(_) | ExprKind::QualifiedName(_) => false,
        }
    }

    fn legacy_input_constant_in_call_result(
        &self,
        callee: &Expr,
        trace: &mut LegacyInputTrace,
    ) -> bool {
        let Some(name) = expr_name(callee) else {
            return false;
        };

        // The focused legacy input call consumes its marker selector and
        // returns the configured value. No other call boundary is allowed to
        // erase marker provenance, including a UDF that returns one directly.
        if self.is_unshadowed_focused_legacy_input_call(&name, callee) {
            return false;
        }

        let Some(function) = self.functions.get(&name).cloned() else {
            return false;
        };
        if !trace.functions.insert(name.clone()) {
            return false;
        }
        let contains = self.with_source_context_ref(function.source_context_id, |analyzer| {
            analyzer.legacy_input_constant_in_function_return(&function.body, trace)
        });
        trace.functions.remove(&name);
        contains
    }

    fn is_unshadowed_focused_legacy_input_call(&self, name: &str, callee: &Expr) -> bool {
        let is_focused_input = matches!(
            self.legacy.resolve_call(name),
            Some(crate::legacy::LegacyResolution::Focused(
                crate::legacy::LegacyRule {
                    kind: crate::legacy::LegacyRuleKind::FocusedInput,
                    ..
                }
            ))
        );
        if !is_focused_input || self.functions.contains_key(name) {
            return false;
        }

        let is_symbol_shadowed = match &callee.kind {
            ExprKind::Identifier(identifier) => self
                .bound_symbol(identifier, callee.span)
                .or_else(|| self.scope.resolve(identifier))
                .is_some(),
            _ => false,
        };
        !is_symbol_shadowed
    }

    fn legacy_input_constant_in_function_return(
        &self,
        body: &FunctionBody,
        trace: &mut LegacyInputTrace,
    ) -> bool {
        match body {
            FunctionBody::Expr(expr) => self.legacy_input_constant_in_expr_inner(expr, trace),
            FunctionBody::Block(statements) => {
                self.legacy_input_constant_in_return_statements(statements, trace)
            }
        }
    }

    fn legacy_input_constant_in_return_statements(
        &self,
        statements: &[Stmt],
        trace: &mut LegacyInputTrace,
    ) -> bool {
        let Some((last, prior)) = statements.split_last() else {
            return false;
        };
        if self.legacy_input_constant_in_statements(prior, trace) {
            return true;
        }
        match &last.kind {
            StmtKind::Expr(expr) => self.legacy_input_constant_in_expr_inner(expr, trace),
            StmtKind::If {
                condition,
                then_branch,
                else_branch,
            } => {
                self.legacy_input_constant_in_expr_inner(condition, trace)
                    || self.legacy_input_constant_in_return_statements(then_branch, trace)
                    || self.legacy_input_constant_in_return_statements(else_branch, trace)
            }
            StmtKind::For {
                from,
                to,
                step,
                body,
                ..
            } => {
                self.legacy_input_constant_in_expr_inner(from, trace)
                    || self.legacy_input_constant_in_expr_inner(to, trace)
                    || step
                        .as_ref()
                        .is_some_and(|step| self.legacy_input_constant_in_expr_inner(step, trace))
                    || self.legacy_input_constant_in_return_statements(body, trace)
            }
            StmtKind::ForIn { iterable, body, .. } => {
                self.legacy_input_constant_in_expr_inner(iterable, trace)
                    || self.legacy_input_constant_in_return_statements(body, trace)
            }
            StmtKind::While { condition, body } => {
                self.legacy_input_constant_in_expr_inner(condition, trace)
                    || self.legacy_input_constant_in_return_statements(body, trace)
            }
            _ => false,
        }
    }

    fn legacy_input_constant_in_statements(
        &self,
        statements: &[Stmt],
        trace: &mut LegacyInputTrace,
    ) -> bool {
        statements.iter().any(|statement| match &statement.kind {
            StmtKind::Expr(expr)
            | StmtKind::Reassign { value: expr, .. }
            | StmtKind::FieldReassign { value: expr, .. } => {
                self.legacy_input_constant_in_expr_inner(expr, trace)
            }
            StmtKind::Decl { value, .. } => {
                self.legacy_input_type_marker(value).is_none()
                    && self.legacy_input_constant_in_expr_inner(value, trace)
            }
            StmtKind::ArrayFieldReassign {
                array,
                index,
                value,
                ..
            } => {
                self.legacy_input_constant_in_expr_inner(array, trace)
                    || self.legacy_input_constant_in_expr_inner(index, trace)
                    || self.legacy_input_constant_in_expr_inner(value, trace)
            }
            StmtKind::TupleDecl { value, .. } => {
                self.legacy_input_constant_in_expr_inner(value, trace)
            }
            StmtKind::If {
                condition,
                then_branch,
                else_branch,
            } => {
                self.legacy_input_constant_in_expr_inner(condition, trace)
                    || self.legacy_input_constant_in_statements(then_branch, trace)
                    || self.legacy_input_constant_in_statements(else_branch, trace)
            }
            StmtKind::For {
                from,
                to,
                step,
                body,
                ..
            } => {
                self.legacy_input_constant_in_expr_inner(from, trace)
                    || self.legacy_input_constant_in_expr_inner(to, trace)
                    || step
                        .as_ref()
                        .is_some_and(|step| self.legacy_input_constant_in_expr_inner(step, trace))
                    || self.legacy_input_constant_in_statements(body, trace)
            }
            StmtKind::ForIn { iterable, body, .. } => {
                self.legacy_input_constant_in_expr_inner(iterable, trace)
                    || self.legacy_input_constant_in_statements(body, trace)
            }
            StmtKind::While { condition, body } => {
                self.legacy_input_constant_in_expr_inner(condition, trace)
                    || self.legacy_input_constant_in_statements(body, trace)
            }
            StmtKind::Function { body, .. } => match body {
                FunctionBody::Expr(expr) => self.legacy_input_constant_in_expr_inner(expr, trace),
                FunctionBody::Block(statements) => {
                    self.legacy_input_constant_in_statements(statements, trace)
                }
            },
            StmtKind::Export(export) => match &export.item {
                pine_syntax::ExportItem::Function { body, .. } => match body {
                    FunctionBody::Expr(expr) => {
                        self.legacy_input_constant_in_expr_inner(expr, trace)
                    }
                    FunctionBody::Block(statements) => {
                        self.legacy_input_constant_in_statements(statements, trace)
                    }
                },
                pine_syntax::ExportItem::Const { value, .. } => {
                    self.legacy_input_constant_in_expr_inner(value, trace)
                }
                pine_syntax::ExportItem::UserType { .. }
                | pine_syntax::ExportItem::Unknown { .. } => false,
            },
            StmtKind::Method(method) => match &method.body {
                FunctionBody::Expr(expr) => self.legacy_input_constant_in_expr_inner(expr, trace),
                FunctionBody::Block(statements) => {
                    self.legacy_input_constant_in_statements(statements, trace)
                }
            },
            StmtKind::Import(_)
            | StmtKind::Library(_)
            | StmtKind::UserType(_)
            | StmtKind::Break
            | StmtKind::Continue
            | StmtKind::Unsupported { .. } => false,
        })
    }

    fn legacy_input_type_marker(&self, expr: &Expr) -> Option<&'static str> {
        self.legacy_input_type_marker_inner(expr, &mut LegacyInputTrace::default())
    }

    fn legacy_input_type_marker_inner(
        &self,
        expr: &Expr,
        trace: &mut LegacyInputTrace,
    ) -> Option<&'static str> {
        if let Some(marker) = self
            .legacy
            .canonical_string_value(self.current_source_context_id(), expr.span)
        {
            return Some(marker);
        }
        let ExprKind::Identifier(name) = &expr.kind else {
            return None;
        };
        let symbol = self
            .bound_symbol(name, expr.span)
            .or_else(|| self.scope.resolve(name))?;
        let initializer = self.symbol_init_exprs.get(&symbol.id)?.clone();
        if !trace.symbols.insert(symbol.id) {
            return None;
        }
        let marker = self.with_source_context_ref(initializer.source_context_id, |analyzer| {
            analyzer.legacy_input_type_marker_inner(&initializer.expr, trace)
        });
        trace.symbols.remove(&symbol.id);
        marker
    }

    pub(super) fn analyze_focused_legacy_call(
        &mut self,
        name: &str,
        callee_span: Span,
        call_span: Span,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
    ) -> FocusedLegacyCallAnalysis {
        let Some(resolution) = self.legacy.resolve_call(name) else {
            return FocusedLegacyCallAnalysis::NotApplicable;
        };
        match resolution {
            crate::legacy::LegacyResolution::Focused(rule) => match rule.kind {
                crate::legacy::LegacyRuleKind::FocusedInput if name == "input" => {
                    self.analyze_focused_legacy_input(rule, callee_span, call_span, args, arg_types)
                }
                crate::legacy::LegacyRuleKind::FocusedOutput => self.analyze_focused_legacy_output(
                    rule,
                    name,
                    callee_span,
                    call_span,
                    args,
                    arg_types,
                ),
                crate::legacy::LegacyRuleKind::FocusedSecurity if name == "security" => self
                    .analyze_focused_legacy_security(rule, callee_span, call_span, args, arg_types),
                crate::legacy::LegacyRuleKind::FocusedExpression
                | crate::legacy::LegacyRuleKind::FocusedCall => self
                    .analyze_focused_legacy_expression(
                        rule,
                        name,
                        callee_span,
                        call_span,
                        args,
                        arg_types,
                    ),
                _ => FocusedLegacyCallAnalysis::NotApplicable,
            },
            crate::legacy::LegacyResolution::UnsupportedKnown(rule)
                if matches!(
                    rule.kind,
                    crate::legacy::LegacyRuleKind::FocusedInput
                        | crate::legacy::LegacyRuleKind::FocusedOutput
                        | crate::legacy::LegacyRuleKind::FocusedExpression
                        | crate::legacy::LegacyRuleKind::FocusedCall
                        | crate::legacy::LegacyRuleKind::FocusedSecurity
                ) =>
            {
                let crate::legacy::LegacyRuleSupport::UnsupportedKnown { reason } = rule.support
                else {
                    unreachable!("legacy resolver preserves rule support state")
                };
                self.unsupported(rule.source_name, reason, callee_span);
                FocusedLegacyCallAnalysis::Analyzed(None)
            }
            _ => FocusedLegacyCallAnalysis::NotApplicable,
        }
    }

    fn analyze_focused_legacy_expression(
        &mut self,
        rule: crate::legacy::LegacyRule,
        name: &str,
        callee_span: Span,
        call_span: Span,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
    ) -> FocusedLegacyCallAnalysis {
        let bound = match self
            .legacy
            .bind_legacy_expression(name, args, arg_types, call_span)
        {
            crate::legacy::LegacyExpressionBinding::Bound(bound) => bound,
            crate::legacy::LegacyExpressionBinding::Invalid(diagnostics) => {
                self.diagnostics.extend(diagnostics);
                return FocusedLegacyCallAnalysis::Analyzed(None);
            }
        };
        let pine_type = match bound.kind {
            crate::legacy::LegacyExpressionKind::Iff => self.analyze_legacy_iff(&bound, call_span),
            crate::legacy::LegacyExpressionKind::Offset => self.analyze_legacy_offset(&bound),
            crate::legacy::LegacyExpressionKind::RsiLength => {
                let mut canonical_args = bound.ordered_args.clone();
                canonical_args[0].name = Some("source".to_owned());
                canonical_args[1].name = Some("length".to_owned());
                let signature = pine_builtins::get_phase_1_builtin("ta.rsi")
                    .expect("canonical RSI signature is registered");
                self.analyze_registered_builtin(
                    "ta.rsi",
                    signature,
                    callee_span,
                    call_span,
                    &canonical_args,
                    &bound
                        .ordered_arg_types
                        .iter()
                        .copied()
                        .map(Some)
                        .collect::<Vec<_>>(),
                )
            }
            crate::legacy::LegacyExpressionKind::RsiSeries => {
                self.analyze_legacy_rsi_series(&bound, call_span)
            }
        };
        let Some(pine_type) = pine_type else {
            return FocusedLegacyCallAnalysis::Analyzed(None);
        };
        let source_context_id = self.current_source_context_id();
        self.legacy.record_expression_translation(
            &mut self.compatibility,
            source_context_id,
            callee_span,
            rule,
            &bound,
        );
        FocusedLegacyCallAnalysis::Analyzed(Some(pine_type))
    }

    fn analyze_focused_legacy_security(
        &mut self,
        rule: crate::legacy::LegacyRule,
        callee_span: Span,
        call_span: Span,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
    ) -> FocusedLegacyCallAnalysis {
        let const_strings = args
            .iter()
            .map(|arg| self.known_const_string_value(&arg.value))
            .collect::<Vec<_>>();
        let const_bools = args
            .iter()
            .map(|arg| self.known_const_bool_value(&arg.value))
            .collect::<Vec<_>>();
        let bound = match self.legacy.bind_legacy_security_args(
            args,
            arg_types,
            &const_strings,
            &const_bools,
            call_span,
        ) {
            crate::legacy::LegacySecurityBinding::Bound(bound) => bound,
            crate::legacy::LegacySecurityBinding::Invalid(diagnostics) => {
                self.diagnostics.extend(diagnostics);
                return FocusedLegacyCallAnalysis::Analyzed(None);
            }
        };
        let unsupported_before = self.compatibility.unsupported.len();
        let pine_type = self.analyze_bound_legacy_security(callee_span, &bound);
        if self.compatibility.unsupported.len() != unsupported_before || pine_type.is_none() {
            return FocusedLegacyCallAnalysis::Analyzed(pine_type);
        }
        let source_context_id = self.current_source_context_id();
        self.legacy.record_security_translation(
            &mut self.compatibility,
            source_context_id,
            callee_span,
            call_span,
            rule,
            &bound,
        );
        FocusedLegacyCallAnalysis::Analyzed(pine_type)
    }

    fn analyze_legacy_iff(
        &mut self,
        bound: &crate::legacy::BoundLegacyExpression,
        call_span: Span,
    ) -> Option<PineType> {
        let [condition_type, then_type, else_type] = bound.ordered_arg_types.as_slice() else {
            unreachable!("validated iff arity")
        };
        self.expect_bool(*condition_type, bound.ordered_args[0].span);
        if !matches!(
            then_type.kind,
            ValueKind::Int
                | ValueKind::Float
                | ValueKind::Bool
                | ValueKind::String
                | ValueKind::Color
                | ValueKind::Na
        ) || !matches!(
            else_type.kind,
            ValueKind::Int
                | ValueKind::Float
                | ValueKind::Bool
                | ValueKind::String
                | ValueKind::Color
                | ValueKind::Na
        ) {
            self.unsupported(
                "iff.result",
                "the current legacy iff slice supports scalar numeric, bool, string, color, and na results",
                call_span,
            );
            return None;
        }
        self.merge_branch_types(
            *condition_type,
            *then_type,
            *else_type,
            self.known_const_bool_value(&bound.ordered_args[0].value),
            call_span,
        )
    }

    fn analyze_legacy_offset(
        &mut self,
        bound: &crate::legacy::BoundLegacyExpression,
    ) -> Option<PineType> {
        let source_type = bound.ordered_arg_types[0];
        if matches!(source_type.kind, ValueKind::Tuple | ValueKind::Void) {
            self.unsupported(
                "offset.source",
                "legacy offset does not support tuple or void source values",
                bound.ordered_args[0].span,
            );
            return None;
        }
        self.validate_history_offset(
            &bound.ordered_args[1].value,
            Some(bound.ordered_arg_types[1]),
        );
        Some(PineType::new(Qualifier::Series, source_type.kind))
    }

    fn analyze_legacy_rsi_series(
        &mut self,
        bound: &crate::legacy::BoundLegacyExpression,
        call_span: Span,
    ) -> Option<PineType> {
        let first = bound.ordered_arg_types[0];
        let second = bound.ordered_arg_types[1];
        if first.qualifier != Qualifier::Series
            || !matches!(first.kind, ValueKind::Int | ValueKind::Float)
            || !matches!(second.kind, ValueKind::Int | ValueKind::Float)
        {
            self.diagnostics.push(Diagnostic::error(
                "E_LEGACY_RSI_OVERLOAD",
                "Pine v4 two-series `rsi(x, y)` requires a series numeric first argument and a numeric second argument",
                call_span,
            ));
            return None;
        }
        Some(PineType::new(Qualifier::Series, ValueKind::Float))
    }

    fn analyze_focused_legacy_input(
        &mut self,
        rule: crate::legacy::LegacyRule,
        callee_span: Span,
        call_span: Span,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
    ) -> FocusedLegacyCallAnalysis {
        let explicit_type_marker = self
            .legacy
            .explicit_legacy_input_type_expr(args)
            .and_then(|expr| self.legacy_input_type_marker(expr).map(str::to_owned));
        let bound = match self.legacy.bind_legacy_input_args(
            args,
            arg_types,
            explicit_type_marker.as_deref(),
        ) {
            crate::legacy::LegacyInputBinding::Bound(bound) => bound,
            crate::legacy::LegacyInputBinding::Invalid(diagnostics) => {
                self.diagnostics.extend(diagnostics);
                return FocusedLegacyCallAnalysis::Analyzed(None);
            }
        };
        let signature = pine_builtins::get_phase_1_builtin(bound.canonical_name)
            .expect("validated focused input target is registered");
        let source_context_id = self.current_source_context_id();
        self.legacy.record_input_translation(
            &mut self.compatibility,
            source_context_id,
            callee_span,
            rule,
            bound.canonical_name,
            bound.arg_rewrites,
        );
        FocusedLegacyCallAnalysis::Analyzed(self.analyze_registered_builtin(
            bound.canonical_name,
            signature,
            callee_span,
            call_span,
            &bound.canonical_args,
            &bound.canonical_arg_types,
        ))
    }

    fn analyze_focused_legacy_output(
        &mut self,
        rule: crate::legacy::LegacyRule,
        name: &str,
        callee_span: Span,
        call_span: Span,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
    ) -> FocusedLegacyCallAnalysis {
        let const_strings = args
            .iter()
            .map(|arg| self.known_const_string_value(&arg.value))
            .collect::<Vec<_>>();
        let const_ints = args
            .iter()
            .map(|arg| self.known_const_int_value(&arg.value))
            .collect::<Vec<_>>();
        let bound = match self.legacy.bind_legacy_output_args(
            name,
            args,
            arg_types,
            &const_strings,
            &const_ints,
        ) {
            crate::legacy::LegacyOutputBinding::Bound(bound) => bound,
            crate::legacy::LegacyOutputBinding::Invalid(diagnostics) => {
                self.diagnostics.extend(diagnostics);
                return FocusedLegacyCallAnalysis::Analyzed(None);
            }
        };
        let signature = pine_builtins::get_phase_1_builtin(bound.canonical_name)
            .expect("validated focused output target is registered");
        let source_context_id = self.current_source_context_id();
        self.legacy.record_output_translation(
            &mut self.compatibility,
            source_context_id,
            callee_span,
            rule,
            crate::legacy::LegacyOutputTranslationPlan {
                canonical_name: bound.canonical_name,
                arg_rewrites: bound.arg_rewrites,
                requires_adaptation: bound.requires_adaptation,
                emulates_transparency: bound.emulates_transparency,
                emulates_numeric_style: bound.emulates_numeric_style,
            },
        );
        FocusedLegacyCallAnalysis::Analyzed(self.analyze_registered_builtin(
            bound.canonical_name,
            signature,
            callee_span,
            call_span,
            &bound.canonical_args,
            &bound.canonical_arg_types,
        ))
    }
}
