use crate::PineDialect;
use crate::prelude::*;

mod legacy_conversions;
mod resolution;
mod type_queries;

#[derive(Debug, Clone)]
struct ForInExprKinds {
    index_kind: Option<ValueKind>,
    value_kind: ValueKind,
    user_type_name: Option<String>,
}

fn for_in_expr_kinds(
    iterable_type: PineType,
    analyzer: &Analyzer,
    iterable: &Expr,
    has_index: bool,
) -> Option<ForInExprKinds> {
    let scalar = |value_kind| {
        Some(ForInExprKinds {
            index_kind: has_index.then_some(ValueKind::Int),
            value_kind,
            user_type_name: None,
        })
    };
    match iterable_type.kind {
        ValueKind::IntArray => scalar(ValueKind::Int),
        ValueKind::FloatArray => scalar(ValueKind::Float),
        ValueKind::BoolArray => scalar(ValueKind::Bool),
        ValueKind::StringArray => scalar(ValueKind::String),
        ValueKind::ColorArray => scalar(ValueKind::Color),
        ValueKind::LabelArray => scalar(ValueKind::Label),
        ValueKind::LineArray => scalar(ValueKind::Line),
        ValueKind::LineFillArray => scalar(ValueKind::LineFill),
        ValueKind::PolylineArray => scalar(ValueKind::Polyline),
        ValueKind::BoxArray => scalar(ValueKind::Box),
        ValueKind::TableArray => scalar(ValueKind::Table),
        ValueKind::ChartPointArray => scalar(ValueKind::ChartPoint),
        ValueKind::UserTypeArray => {
            analyzer
                .user_type_array_name_of_expr(iterable)
                .map(|type_name| ForInExprKinds {
                    index_kind: has_index.then_some(ValueKind::Int),
                    value_kind: ValueKind::UserType,
                    user_type_name: Some(type_name),
                })
        }
        ValueKind::FloatMatrix => scalar(ValueKind::FloatArray),
        ValueKind::IntMatrix => scalar(ValueKind::IntArray),
        ValueKind::BoolMatrix => scalar(ValueKind::BoolArray),
        ValueKind::StringMatrix => scalar(ValueKind::StringArray),
        ValueKind::ColorMatrix => scalar(ValueKind::ColorArray),
        ValueKind::Map => {
            let info = analyzer.map_type_of_expr(iterable)?;
            Some(ForInExprKinds {
                index_kind: has_index.then_some(info.key_kind),
                value_kind: if has_index {
                    info.value_kind
                } else {
                    info.key_kind
                },
                user_type_name: None,
            })
        }
        _ => None,
    }
}

impl Analyzer {
    pub(crate) fn analyze_expr(&mut self, expr: &Expr) -> Option<PineType> {
        // Function and method bodies can be analyzed repeatedly with different
        // argument templates and UDT identities. Discard span-keyed collection
        // metadata from an earlier pass before deriving the current result.
        let key = self.expr_key(expr.span);
        self.expr_maps.remove(&key);
        self.expr_user_type_arrays.remove(&key);
        if !self.enter_expr_analysis(expr.span) {
            return None;
        }

        let result = self.analyze_expr_inner(expr);
        self.exit_expr_analysis();
        result
    }

    fn analyze_expr_inner(&mut self, expr: &Expr) -> Option<PineType> {
        match &expr.kind {
            ExprKind::Literal(literal) => {
                if matches!(literal, Literal::ColorHex(_)) {
                    self.compatibility.supported.push(FeatureUse {
                        feature: "hex color literal".to_owned(),
                        span: expr.span,
                    });
                }
                Some(literal_type(literal))
            }
            ExprKind::Identifier(name) => {
                self.check_feature_expr(expr);
                let pine_type = self.resolve_symbol(name, expr.span);
                if pine_type.is_some_and(|pine_type| pine_type.kind == ValueKind::Map)
                    && let Some(info) = self.map_type_of_current_symbol(name)
                {
                    self.mark_expr_map(expr.span, info);
                }
                if pine_type.is_some_and(|pine_type| pine_type.kind == ValueKind::UserTypeArray)
                    && let Some(type_name) = self.user_type_array_name_of_current_symbol(name)
                {
                    self.mark_expr_user_type_array(expr.span, type_name);
                }
                pine_type
            }
            ExprKind::QualifiedName(parts) => {
                if let Some(field_type) = self.resolve_chart_point_field_access(parts, expr.span) {
                    return Some(field_type);
                }
                if let Some(field_type) = self.resolve_user_type_field_access(parts, expr.span) {
                    return Some(field_type);
                }
                let name = expr_name(expr)?;
                self.resolve_qualified_value(&name, expr.span)
            }
            ExprKind::Unary { op, expr: operand } => {
                let expr_type = self.analyze_expr(operand)?;
                self.infer_unary_with_legacy(*op, expr_type, operand.span, expr.span)
            }
            ExprKind::Binary { op, left, right } => {
                let left_type = self.analyze_expr(left);
                let right_type = self.analyze_expr(right);
                match (left_type, right_type) {
                    (Some(left_type), Some(right_type)) => self.infer_binary_with_legacy(
                        *op, left_type, right_type, left.span, right.span, expr.span,
                    ),
                    _ => None,
                }
            }
            ExprKind::Ternary {
                condition,
                then_expr,
                else_expr,
            } => {
                let condition_type = self.analyze_expr(condition);
                if let Some(condition_type) = condition_type {
                    self.expect_bool(condition_type, condition.span);
                }
                let then_type = self.analyze_expr(then_expr);
                let else_type = self.analyze_expr(else_expr);
                match (condition_type, then_type, else_type) {
                    (Some(condition_type), Some(then_type), Some(else_type)) => {
                        let pine_type = self.merge_branch_types(
                            condition_type,
                            then_type,
                            else_type,
                            self.known_const_bool_value(condition),
                            expr.span,
                        )?;
                        if pine_type.kind == ValueKind::UserType
                            && !self.mark_ternary_user_type(expr.span, then_expr, else_expr)
                        {
                            self.diagnostics.push(Diagnostic::error(
                                "E_BRANCH_TYPE",
                                "ternary user-defined type branches must resolve to the same UDT identity",
                                expr.span,
                            ));
                            return None;
                        }
                        if pine_type.kind == ValueKind::Map
                            && !self.mark_ternary_map(expr.span, then_expr, else_expr)
                        {
                            self.diagnostics.push(Diagnostic::error(
                                "E_BRANCH_TYPE",
                                "ternary map branches must resolve to the same map template",
                                expr.span,
                            ));
                            return None;
                        }
                        if pine_type.kind == ValueKind::UserTypeArray
                            && !self.mark_ternary_user_type_array(expr.span, then_expr, else_expr)
                        {
                            self.diagnostics.push(Diagnostic::error(
                                "E_BRANCH_TYPE",
                                "ternary UDT array branches must resolve to the same element identity",
                                expr.span,
                            ));
                            return None;
                        }
                        Some(pine_type)
                    }
                    _ => None,
                }
            }
            ExprKind::If {
                condition,
                then_branch,
                else_branch,
            } => self.analyze_if_expr(condition, then_branch, else_branch, expr.span),
            ExprKind::Switch { selector, arms } => {
                self.analyze_switch_expr(selector.as_deref(), arms, expr.span)
            }
            ExprKind::For {
                counter,
                from,
                to,
                step,
                body,
            } => self.analyze_for_expr(counter, from, to, step.as_deref(), body, expr.span),
            ExprKind::ForIn {
                index,
                value,
                iterable,
                body,
            } => self.analyze_for_in_expr(index.as_deref(), value, iterable, body, expr.span),
            ExprKind::While { condition, body } => {
                self.analyze_while_expr(condition, body, expr.span)
            }
            ExprKind::Tuple(items) => {
                for item in items {
                    self.analyze_expr(item);
                }
                Some(pine_builtins::tuple_return_type())
            }
            ExprKind::Call { callee, args } => {
                let pine_type = self.analyze_call(callee, args, expr.span);
                if let Some(pine_type) = pine_type {
                    let key = self.expr_key(expr.span);
                    self.expr_types.insert(key, pine_type);
                }
                pine_type
            }
            ExprKind::History {
                expr: value_expr,
                offset,
            } => {
                let value_type = self.analyze_expr(value_expr);
                let offset_type = self.analyze_expr(offset);
                self.validate_history_offset(offset, offset_type);
                if matches!(
                    value_type.map(|pine_type| pine_type.kind),
                    Some(ValueKind::UserType)
                ) {
                    if let Some(type_name) =
                        self.user_type_name_of_expr(value_expr).filter(|type_name| {
                            self.imported_user_type_history_is_supported(type_name)
                                || self.local_user_type_history_is_supported(type_name)
                        })
                    {
                        self.mark_expr_user_type(expr.span, type_name);
                        return value_type
                            .map(|value_type| PineType::new(Qualifier::Series, value_type.kind));
                    }
                    self.unsupported(
                        "user-defined type history",
                        "history references on user-defined type values are not supported in the current UDT subset",
                        value_expr.span,
                    );
                    return None;
                }
                if matches!(
                    value_type.map(|pine_type| pine_type.kind),
                    Some(ValueKind::Map)
                ) && let Some(info) = self.map_type_of_expr(value_expr)
                {
                    self.mark_expr_map(expr.span, info);
                }
                if matches!(
                    value_type.map(|pine_type| pine_type.kind),
                    Some(ValueKind::UserTypeArray)
                ) && let Some(type_name) = self.user_type_array_name_of_expr(value_expr)
                {
                    self.mark_expr_user_type_array(expr.span, type_name);
                }
                value_type.map(|value_type| PineType::new(Qualifier::Series, value_type.kind))
            }
        }
    }

    pub(crate) fn analyze_if_expr(
        &mut self,
        condition: &Expr,
        then_branch: &[Stmt],
        else_branch: &[Stmt],
        span: Span,
    ) -> Option<PineType> {
        let condition_type = self.analyze_expr(condition);
        if let Some(condition_type) = condition_type {
            self.expect_bool(condition_type, condition.span);
        }
        let condition_qualifier =
            condition_type.map_or(Qualifier::Const, |pine_type| pine_type.qualifier);

        self.compatibility.supported.push(FeatureUse {
            feature: "if".to_owned(),
            span,
        });

        let condition_value = self.known_const_bool_value(condition);
        self.block_depth += 1;
        self.assignment_qualifier_context.push(condition_qualifier);
        let (then_type, else_type) = match condition_value {
            Some(true) => {
                let then_type = self.analyze_expr_branch_return(then_branch, "if", span, true);
                let else_type = self.analyze_without_symbol_effects(|analyzer| {
                    analyzer.analyze_expr_branch_return(else_branch, "if", span, true)
                });
                (then_type, else_type)
            }
            Some(false) => {
                let then_type = self.analyze_without_symbol_effects(|analyzer| {
                    analyzer.analyze_expr_branch_return(then_branch, "if", span, true)
                });
                let else_type = self.analyze_expr_branch_return(else_branch, "if", span, true);
                (then_type, else_type)
            }
            None => {
                let then_type = self.analyze_expr_branch_return(then_branch, "if", span, true);
                let else_type = self.analyze_expr_branch_return(else_branch, "if", span, true);
                (then_type, else_type)
            }
        };
        self.assignment_qualifier_context.pop();
        self.block_depth -= 1;

        match (condition_type, then_type, else_type) {
            (Some(condition_type), Some(then_type), Some(else_type)) => {
                let pine_type = self.merge_branch_types(
                    condition_type,
                    then_type,
                    else_type,
                    condition_value,
                    span,
                )?;
                if pine_type.kind == ValueKind::UserType {
                    let type_name = self.user_type_name_of_if_branches(then_branch, else_branch);
                    if let Some(type_name) = type_name {
                        self.mark_expr_user_type(span, type_name);
                    } else {
                        self.diagnostics.push(Diagnostic::error(
                            "E_BRANCH_TYPE",
                            "if user-defined type branches must resolve to the same UDT identity",
                            span,
                        ));
                        return None;
                    }
                }
                if pine_type.kind == ValueKind::Map
                    && !self.mark_if_map(span, then_branch, else_branch)
                {
                    self.diagnostics.push(Diagnostic::error(
                        "E_BRANCH_TYPE",
                        "if map branches must resolve to the same map template",
                        span,
                    ));
                    return None;
                }
                if pine_type.kind == ValueKind::UserTypeArray
                    && !self.mark_if_user_type_array(span, then_branch, else_branch)
                {
                    self.diagnostics.push(Diagnostic::error(
                        "E_BRANCH_TYPE",
                        "if UDT array branches must resolve to the same element identity",
                        span,
                    ));
                    return None;
                }
                Some(pine_type)
            }
            _ => None,
        }
    }

    fn analyze_expr_branch_return(
        &mut self,
        branch: &[Stmt],
        keyword: &str,
        span: Span,
        allow_final_loop: bool,
    ) -> Option<PineType> {
        let Some((last, prefix)) = branch.split_last() else {
            self.diagnostics.push(Diagnostic::error(
                "E_BRANCH_RETURN",
                format!("{keyword} expression branches must end with a value-producing expression"),
                span,
            ));
            return None;
        };

        self.scope.push_scope();
        for statement in prefix {
            self.analyze_stmt(statement);
        }
        let pine_type = match &last.kind {
            StmtKind::Expr(expr) => {
                let pine_type = self.analyze_expr(expr);
                if matches!(
                    pine_type,
                    Some(PineType {
                        kind: ValueKind::Void,
                        ..
                    })
                ) {
                    self.diagnostics.push(Diagnostic::error(
                        "E_BRANCH_RETURN",
                        format!("{keyword} expression branches must end with a value-producing expression"),
                        expr.span,
                    ));
                    None
                } else {
                    pine_type
                }
            }
            StmtKind::For {
                counter,
                from,
                to,
                step,
                body,
            } if allow_final_loop => {
                self.analyze_for_expr(counter, from, to, step.as_ref(), body, last.span)
            }
            StmtKind::ForIn {
                index,
                value,
                iterable,
                body,
            } if allow_final_loop => {
                self.analyze_for_in_expr(index.as_deref(), value, iterable, body, last.span)
            }
            StmtKind::While { condition, body } if allow_final_loop => {
                self.analyze_while_expr(condition, body, last.span)
            }
            _ => {
                self.analyze_stmt(last);
                self.diagnostics.push(Diagnostic::error(
                    "E_BRANCH_RETURN",
                    format!(
                        "{keyword} expression branches must end with a value-producing expression"
                    ),
                    last.span,
                ));
                None
            }
        };
        self.scope.pop_scope();
        pine_type
    }

    fn analyze_loop_expr_body_return(&mut self, last: &Stmt, keyword: &str) -> Option<PineType> {
        match &last.kind {
            StmtKind::Expr(expr) => {
                let pine_type = self.analyze_expr(expr);
                if matches!(
                    pine_type,
                    Some(PineType {
                        kind: ValueKind::Void,
                        ..
                    })
                ) {
                    self.diagnostics.push(Diagnostic::error(
                        "E_LOOP_RETURN",
                        format!(
                            "{keyword} expression body must end with a value-producing expression"
                        ),
                        expr.span,
                    ));
                    None
                } else {
                    pine_type
                }
            }
            StmtKind::For {
                counter,
                from,
                to,
                step,
                body,
            } => self.analyze_for_expr(counter, from, to, step.as_ref(), body, last.span),
            StmtKind::ForIn {
                index,
                value,
                iterable,
                body,
            } => self.analyze_for_in_expr(index.as_deref(), value, iterable, body, last.span),
            StmtKind::While { condition, body } => {
                self.analyze_while_expr(condition, body, last.span)
            }
            _ => {
                self.analyze_stmt(last);
                self.diagnostics.push(Diagnostic::error(
                    "E_LOOP_RETURN",
                    format!("{keyword} expression body must end with a value-producing expression"),
                    last.span,
                ));
                None
            }
        }
    }

    fn enter_expr_analysis(&mut self, span: Span) -> bool {
        if self.expr_depth >= MAX_SEMA_EXPR_DEPTH {
            self.diagnostics.push(Diagnostic::error(
                "E_SEMA_EXPR_DEPTH",
                "expression is too deeply nested for semantic analysis",
                span,
            ));
            return false;
        }

        self.expr_depth += 1;
        true
    }

    fn exit_expr_analysis(&mut self) {
        self.expr_depth = self.expr_depth.saturating_sub(1);
    }

    pub(crate) fn analyze_switch_expr(
        &mut self,
        selector: Option<&Expr>,
        arms: &[SwitchArm],
        span: Span,
    ) -> Option<PineType> {
        let selector_type = selector.and_then(|selector| self.analyze_expr(selector));
        let selector_key = selector.and_then(|selector| self.known_const_switch_key(selector));
        let selector_qualifier = selector_type.map_or(Qualifier::Const, |ty| ty.qualifier);
        let mut reachable_condition_qualifier = selector_qualifier;
        let mut result_type = None;
        let mut selected_result_type = None;
        let mut static_selection_open = selector.is_none() || selector_key.is_some();
        let mut dynamic_tail = selector.is_some() && selector_key.is_none();
        let mut has_type_error = false;

        self.compatibility.supported.push(FeatureUse {
            feature: "switch".to_owned(),
            span,
        });

        for arm in arms {
            let arm_reachable = dynamic_tail || static_selection_open;
            let condition_value = if selector.is_none() {
                arm.condition
                    .as_ref()
                    .and_then(|condition| self.known_const_bool_value(condition))
            } else {
                None
            };
            let case_key = if selector.is_some() {
                arm.condition
                    .as_ref()
                    .and_then(|condition| self.known_const_switch_key(condition))
            } else {
                None
            };
            let mut arm_qualifier = selector_qualifier;
            if let Some(condition) = &arm.condition {
                let condition_type = self.analyze_expr(condition);
                if let Some(condition_type) = condition_type {
                    arm_qualifier = strongest_qualifier(arm_qualifier, condition_type.qualifier);
                    if arm_reachable {
                        reachable_condition_qualifier = strongest_qualifier(
                            reachable_condition_qualifier,
                            condition_type.qualifier,
                        );
                    }
                    if selector.is_none() {
                        self.expect_bool(condition_type, condition.span);
                    }
                }
            }
            if arm_reachable {
                arm_qualifier = reachable_condition_qualifier;
            }

            let mut statically_selected = false;
            let commit_symbol_effects = if dynamic_tail {
                true
            } else if !static_selection_open {
                false
            } else if selector.is_none() {
                match (&arm.condition, condition_value) {
                    (Some(_), Some(false)) => false,
                    (Some(_), Some(true)) | (None, _) => {
                        static_selection_open = false;
                        statically_selected = true;
                        true
                    }
                    (Some(_), None) => {
                        static_selection_open = false;
                        dynamic_tail = true;
                        true
                    }
                }
            } else if let Some(selector_key) = selector_key.as_ref() {
                match (&arm.condition, case_key.as_ref()) {
                    (Some(_), Some(case_key)) if case_key == selector_key => {
                        static_selection_open = false;
                        statically_selected = true;
                        true
                    }
                    (Some(_), Some(_)) => false,
                    (Some(_), None) => {
                        static_selection_open = false;
                        dynamic_tail = true;
                        true
                    }
                    (None, _) => {
                        static_selection_open = false;
                        statically_selected = true;
                        true
                    }
                }
            } else {
                true
            };

            let arm_type = if commit_symbol_effects {
                self.assignment_qualifier_context.push(arm_qualifier);
                let arm_type = self.analyze_switch_arm_result(&arm.result, span);
                self.assignment_qualifier_context.pop();
                arm_type
            } else {
                self.analyze_without_symbol_effects(|analyzer| {
                    analyzer.assignment_qualifier_context.push(arm_qualifier);
                    let arm_type = analyzer.analyze_switch_arm_result(&arm.result, span);
                    analyzer.assignment_qualifier_context.pop();
                    arm_type
                })
            };

            if let Some(arm_type) = arm_type {
                if statically_selected && selected_result_type.is_none() {
                    selected_result_type = Some(arm_type);
                }
                match merge_result_types(result_type, arm_type) {
                    Some(merged) => result_type = Some(merged),
                    None => {
                        self.diagnostics.push(Diagnostic::error(
                            "E_BRANCH_TYPE",
                            format!(
                                "switch arms have incompatible types {} and {}",
                                value_kind_name(result_type.unwrap_or(UNKNOWN).kind),
                                value_kind_name(arm_type.kind)
                            ),
                            span,
                        ));
                        has_type_error = true;
                    }
                }
            }
        }

        if has_type_error {
            return None;
        }

        result_type.and_then(|pine_type| {
            let branch_qualifier =
                selected_result_type.map_or(pine_type.qualifier, |ty: PineType| ty.qualifier);
            let pine_type = PineType::new(
                strongest_qualifier(reachable_condition_qualifier, branch_qualifier),
                pine_type.kind,
            );
            if pine_type.kind == ValueKind::UserType && !self.mark_switch_user_type(span, arms) {
                self.diagnostics.push(Diagnostic::error(
                    "E_BRANCH_TYPE",
                    "switch user-defined type arms must resolve to the same UDT identity",
                    span,
                ));
                return None;
            }
            if pine_type.kind == ValueKind::Map && !self.mark_switch_map(span, arms) {
                self.diagnostics.push(Diagnostic::error(
                    "E_BRANCH_TYPE",
                    "switch map arms must resolve to the same map template",
                    span,
                ));
                return None;
            }
            if pine_type.kind == ValueKind::UserTypeArray
                && !self.mark_switch_user_type_array(span, arms)
            {
                self.diagnostics.push(Diagnostic::error(
                    "E_BRANCH_TYPE",
                    "switch UDT array arms must resolve to the same element identity",
                    span,
                ));
                return None;
            }
            Some(pine_type)
        })
    }

    fn analyze_switch_arm_result(
        &mut self,
        result: &SwitchArmResult,
        span: Span,
    ) -> Option<PineType> {
        match result {
            SwitchArmResult::Expr(expr) => self.analyze_expr(expr),
            SwitchArmResult::Block(statements) => {
                self.block_depth += 1;
                let result = self.analyze_expr_branch_return(statements, "switch", span, true);
                self.block_depth -= 1;
                result
            }
        }
    }

    pub(crate) fn analyze_switch_stmt(
        &mut self,
        selector: Option<&Expr>,
        arms: &[SwitchArm],
        span: Span,
    ) {
        let selector_type = selector.and_then(|selector| self.analyze_expr(selector));
        let selector_key = selector.and_then(|selector| self.known_const_switch_key(selector));
        let selector_qualifier = selector_type.map_or(Qualifier::Const, |ty| ty.qualifier);
        let mut reachable_condition_qualifier = selector_qualifier;
        let mut static_selection_open = selector.is_none() || selector_key.is_some();
        let mut dynamic_tail = selector.is_some() && selector_key.is_none();
        self.compatibility.supported.push(FeatureUse {
            feature: "switch".to_owned(),
            span,
        });

        for arm in arms {
            let arm_reachable = dynamic_tail || static_selection_open;
            let condition_value = if selector.is_none() {
                arm.condition
                    .as_ref()
                    .and_then(|condition| self.known_const_bool_value(condition))
            } else {
                None
            };
            let case_key = if selector.is_some() {
                arm.condition
                    .as_ref()
                    .and_then(|condition| self.known_const_switch_key(condition))
            } else {
                None
            };
            let mut arm_qualifier = selector_qualifier;
            if let Some(condition) = &arm.condition
                && let Some(condition_type) = self.analyze_expr(condition)
            {
                arm_qualifier = strongest_qualifier(arm_qualifier, condition_type.qualifier);
                if arm_reachable {
                    reachable_condition_qualifier = strongest_qualifier(
                        reachable_condition_qualifier,
                        condition_type.qualifier,
                    );
                }
                if selector.is_none() {
                    self.expect_bool(condition_type, condition.span);
                }
            }
            if arm_reachable {
                arm_qualifier = reachable_condition_qualifier;
            }

            let commit_symbol_effects = if dynamic_tail {
                true
            } else if !static_selection_open {
                false
            } else if selector.is_none() {
                match (&arm.condition, condition_value) {
                    (Some(_), Some(false)) => false,
                    (Some(_), Some(true)) | (None, _) => {
                        static_selection_open = false;
                        true
                    }
                    (Some(_), None) => {
                        dynamic_tail = true;
                        true
                    }
                }
            } else if let Some(selector_key) = selector_key.as_ref() {
                match (&arm.condition, case_key.as_ref()) {
                    (Some(_), Some(case_key)) if case_key == selector_key => {
                        static_selection_open = false;
                        true
                    }
                    (Some(_), Some(_)) => false,
                    (Some(_), None) => {
                        dynamic_tail = true;
                        true
                    }
                    (None, _) => {
                        static_selection_open = false;
                        true
                    }
                }
            } else {
                true
            };

            if commit_symbol_effects {
                self.analyze_switch_stmt_arm_result(&arm.result, arm_qualifier);
            } else {
                self.analyze_without_symbol_effects(|analyzer| {
                    analyzer.analyze_switch_stmt_arm_result(&arm.result, arm_qualifier);
                });
            }
        }
    }

    fn analyze_switch_stmt_arm_result(
        &mut self,
        result: &SwitchArmResult,
        arm_qualifier: Qualifier,
    ) {
        match result {
            SwitchArmResult::Expr(expr) => {
                self.analyze_expr(expr);
            }
            SwitchArmResult::Block(statements) => {
                self.block_depth += 1;
                self.assignment_qualifier_context.push(arm_qualifier);
                self.scope.push_scope();
                for statement in statements {
                    self.analyze_stmt(statement);
                }
                self.scope.pop_scope();
                self.assignment_qualifier_context.pop();
                self.block_depth -= 1;
            }
        }
    }

    pub(crate) fn analyze_for_expr(
        &mut self,
        counter: &str,
        from: &Expr,
        to: &Expr,
        step: Option<&Expr>,
        body: &[Stmt],
        span: Span,
    ) -> Option<PineType> {
        let from_type = self.analyze_expr(from);
        let to_type = self.analyze_expr(to);
        let step_type = step.and_then(|step| self.analyze_expr(step));
        if let Some(from_type) = from_type {
            self.expect_int(from_type, from.span);
        }
        if let Some(to_type) = to_type {
            self.expect_int(to_type, to.span);
        }
        if let Some((step, step_type)) = step.zip(step_type) {
            self.expect_int(step_type, step.span);
            self.expect_non_zero_loop_step(step);
        }

        self.compatibility.supported.push(FeatureUse {
            feature: "for".to_owned(),
            span,
        });

        let loop_qualifier = [from_type, to_type, step_type]
            .into_iter()
            .flatten()
            .map(|pine_type| pine_type.qualifier)
            .fold(Qualifier::Const, strongest_qualifier);
        let counter_type = PineType::new(loop_qualifier, ValueKind::Int);
        self.block_depth += 1;
        self.loop_depth += 1;
        self.assignment_qualifier_context.push(loop_qualifier);
        self.scope.push_scope();
        let counter_symbol =
            self.define_local_symbol(counter, counter_type, None, self.function_depth == 0);
        self.bind_symbol(counter, span, counter_symbol);
        self.symbol_tuple_element_types.remove(&counter_symbol.id);
        self.symbol_tuple_user_type_arrays
            .remove(&counter_symbol.id);

        let mut return_type = if let Some((last, prefix)) = body.split_last() {
            for statement in prefix {
                self.analyze_stmt(statement);
            }
            self.analyze_loop_expr_body_return(last, "for")
        } else {
            self.diagnostics.push(Diagnostic::error(
                "E_LOOP_RETURN",
                "for expression body must end with a value-producing expression",
                span,
            ));
            None
        };

        if return_type.is_some_and(|pine_type| pine_type.kind == ValueKind::Map)
            && !self.mark_loop_map(span, body)
        {
            self.diagnostics.push(Diagnostic::error(
                "E_LOOP_RETURN",
                "for expression map result must resolve to a known map template",
                span,
            ));
            return_type = None;
        }
        if return_type.is_some_and(|pine_type| pine_type.kind == ValueKind::UserTypeArray)
            && !self.mark_loop_user_type_array(span, body)
        {
            self.diagnostics.push(Diagnostic::error(
                "E_LOOP_RETURN",
                "for expression UDT array result must resolve to a known element identity",
                span,
            ));
            return_type = None;
        }

        self.scope.pop_scope();
        self.assignment_qualifier_context.pop();
        self.loop_depth -= 1;
        self.block_depth -= 1;
        return_type.map(|pine_type| {
            PineType::new(
                strongest_qualifier(loop_qualifier, pine_type.qualifier),
                pine_type.kind,
            )
        })
    }

    pub(crate) fn analyze_for_in_expr(
        &mut self,
        index: Option<&str>,
        value: &str,
        iterable: &Expr,
        body: &[Stmt],
        span: Span,
    ) -> Option<PineType> {
        let Some(iterable_type) = self.analyze_expr(iterable) else {
            self.unsupported(
                "for...in expression",
                "for...in expressions currently support array<int>, array<float>, array<bool>, array<string>, array<color>, array<label>, array<line>, array<linefill>, array<polyline>, array<box>, array<table>, array<chart.point>, same-local or same-imported scalar-tree UDT array, matrix iterables, and scalar maps with key-only or key/value loop variables",
                span,
            );
            return None;
        };
        let Some(kinds) = for_in_expr_kinds(iterable_type, self, iterable, index.is_some()) else {
            self.unsupported(
                "for...in expression",
                "for...in expressions currently support array<int>, array<float>, array<bool>, array<string>, array<color>, array<label>, array<line>, array<linefill>, array<polyline>, array<box>, array<table>, array<chart.point>, same-local or same-imported scalar-tree UDT array, matrix iterables, and scalar maps with key-only or key/value loop variables",
                span,
            );
            return None;
        };

        self.compatibility.supported.push(FeatureUse {
            feature: "for".to_owned(),
            span,
        });

        self.block_depth += 1;
        self.loop_depth += 1;
        self.assignment_qualifier_context
            .push(iterable_type.qualifier);
        self.scope.push_scope();
        if let Some(index) = index {
            let index_symbol = self.define_local_symbol(
                index,
                PineType::new(
                    Qualifier::Series,
                    kinds.index_kind.unwrap_or(ValueKind::Int),
                ),
                None,
                self.function_depth == 0,
            );
            self.bind_symbol(index, span, index_symbol);
            self.symbol_tuple_element_types.remove(&index_symbol.id);
            self.symbol_tuple_user_type_arrays.remove(&index_symbol.id);
        }
        let value_symbol = self.define_local_symbol(
            value,
            PineType::new(Qualifier::Series, kinds.value_kind),
            None,
            self.function_depth == 0,
        );
        self.bind_symbol(value, span, value_symbol);
        self.symbol_tuple_element_types.remove(&value_symbol.id);
        self.symbol_tuple_user_type_arrays.remove(&value_symbol.id);
        if let Some(type_name) = kinds.user_type_name {
            self.mark_symbol_id_user_type(value_symbol.id, type_name);
        }

        let mut return_type = if let Some((last, prefix)) = body.split_last() {
            for statement in prefix {
                self.analyze_stmt(statement);
            }
            match &last.kind {
                StmtKind::Expr(expr) => {
                    let pine_type = self.analyze_expr(expr);
                    if matches!(
                        pine_type,
                        Some(PineType {
                            kind: ValueKind::Void,
                            ..
                        })
                    ) {
                        self.diagnostics.push(Diagnostic::error(
                            "E_LOOP_RETURN",
                            "for...in expression body must end with a value-producing expression",
                            expr.span,
                        ));
                        None
                    } else if matches!(
                        pine_type,
                        Some(PineType {
                            kind: ValueKind::UserType,
                            ..
                        })
                    ) {
                        if let Some(type_name) = self.user_type_name_of_expr(expr) {
                            self.mark_expr_user_type(span, type_name);
                            pine_type
                        } else {
                            self.diagnostics.push(Diagnostic::error(
                                "E_LOOP_RETURN",
                                "for...in expression user-defined type result must resolve to a known same-local UDT identity",
                                expr.span,
                            ));
                            None
                        }
                    } else {
                        pine_type
                    }
                }
                StmtKind::For {
                    counter,
                    from,
                    to,
                    step,
                    body,
                } => self.analyze_for_expr(counter, from, to, step.as_ref(), body, last.span),
                StmtKind::ForIn {
                    index,
                    value,
                    iterable,
                    body,
                } => self.analyze_for_in_expr(index.as_deref(), value, iterable, body, last.span),
                StmtKind::While { condition, body } => {
                    self.analyze_while_expr(condition, body, last.span)
                }
                _ => {
                    self.analyze_stmt(last);
                    self.diagnostics.push(Diagnostic::error(
                        "E_LOOP_RETURN",
                        "for...in expression body must end with a value-producing expression",
                        last.span,
                    ));
                    None
                }
            }
        } else {
            self.diagnostics.push(Diagnostic::error(
                "E_LOOP_RETURN",
                "for...in expression body must end with a value-producing expression",
                span,
            ));
            None
        };

        if return_type.is_some_and(|pine_type| pine_type.kind == ValueKind::Map)
            && !self.mark_loop_map(span, body)
        {
            self.diagnostics.push(Diagnostic::error(
                "E_LOOP_RETURN",
                "for...in expression map result must resolve to a known map template",
                span,
            ));
            return_type = None;
        }
        if return_type.is_some_and(|pine_type| pine_type.kind == ValueKind::UserTypeArray)
            && !self.mark_loop_user_type_array(span, body)
        {
            self.diagnostics.push(Diagnostic::error(
                "E_LOOP_RETURN",
                "for...in expression UDT array result must resolve to a known element identity",
                span,
            ));
            return_type = None;
        }

        self.scope.pop_scope();
        self.assignment_qualifier_context.pop();
        self.loop_depth -= 1;
        self.block_depth -= 1;
        return_type.map(|pine_type| {
            PineType::new(
                strongest_qualifier(iterable_type.qualifier, pine_type.qualifier),
                pine_type.kind,
            )
        })
    }

    pub(crate) fn analyze_while_expr(
        &mut self,
        condition: &Expr,
        body: &[Stmt],
        span: Span,
    ) -> Option<PineType> {
        let condition_type = self.analyze_expr(condition);
        if let Some(condition_type) = condition_type {
            self.expect_bool(condition_type, condition.span);
        }
        self.compatibility.supported.push(FeatureUse {
            feature: "while".to_owned(),
            span,
        });

        let condition_qualifier =
            condition_type.map_or(Qualifier::Const, |pine_type| pine_type.qualifier);
        self.block_depth += 1;
        self.loop_depth += 1;
        self.assignment_qualifier_context.push(condition_qualifier);
        let mut return_type = self.analyze_expr_branch_return(body, "while", span, true);
        if return_type.is_some_and(|pine_type| pine_type.kind == ValueKind::Map)
            && !self.mark_loop_map(span, body)
        {
            self.diagnostics.push(Diagnostic::error(
                "E_LOOP_RETURN",
                "while expression map result must resolve to a known map template",
                span,
            ));
            return_type = None;
        }
        if return_type.is_some_and(|pine_type| pine_type.kind == ValueKind::UserTypeArray)
            && !self.mark_loop_user_type_array(span, body)
        {
            self.diagnostics.push(Diagnostic::error(
                "E_LOOP_RETURN",
                "while expression UDT array result must resolve to a known element identity",
                span,
            ));
            return_type = None;
        }
        self.assignment_qualifier_context.pop();
        self.loop_depth -= 1;
        self.block_depth -= 1;

        return_type.map(|pine_type| {
            PineType::new(
                strongest_qualifier(condition_qualifier, pine_type.qualifier),
                pine_type.kind,
            )
        })
    }

    pub(crate) fn validate_history_offset(&mut self, offset: &Expr, offset_type: Option<PineType>) {
        if let Some(value) = self.known_history_offset_int_value(offset) {
            if value < 0 {
                self.unsupported(
                    "negative_history_offset",
                    "history offsets must be non-negative in the current supported subset",
                    offset.span,
                );
            }
            return;
        }

        let Some(offset_type) = offset_type else {
            self.unsupported(
                "dynamic_history_offset",
                "dynamic history offsets require an integer expression in the current supported subset",
                offset.span,
            );
            return;
        };

        if offset_type.kind == ValueKind::Int {
            return;
        }

        let actual = pine_type_name(offset_type);
        self.unsupported(
            "dynamic_history_offset",
            &format!(
                "dynamic history offsets require an integer expression in the current supported subset; got {actual}"
            ),
            offset.span,
        );
    }

    pub(crate) fn validate_assignment(
        &mut self,
        name: &str,
        target_type: PineType,
        value_type: PineType,
        span: Span,
    ) {
        if !can_assign(target_type, value_type) {
            self.diagnostics.push(Diagnostic::error(
                "E_ASSIGN_TYPE",
                format!(
                    "cannot assign {} to `{}` of type {}",
                    pine_type_name(value_type),
                    name,
                    pine_type_name(target_type)
                ),
                span,
            ));
        }
    }

    pub(crate) fn infer_unary(
        &mut self,
        op: UnaryOp,
        expr_type: PineType,
        span: Span,
    ) -> Option<PineType> {
        match op {
            UnaryOp::Plus | UnaryOp::Minus if is_numeric(expr_type.kind) => Some(expr_type),
            UnaryOp::Not if expr_type.kind == ValueKind::Bool => Some(expr_type),
            _ => {
                let expected = match op {
                    UnaryOp::Plus | UnaryOp::Minus => "numeric",
                    UnaryOp::Not => "bool",
                };
                self.unary_operator_error(op, expected, expr_type, span);
                None
            }
        }
    }

    pub(crate) fn infer_binary(
        &mut self,
        op: BinaryOp,
        left_type: PineType,
        right_type: PineType,
        span: Span,
    ) -> Option<PineType> {
        match op {
            BinaryOp::Add => {
                if left_type.kind == ValueKind::String && right_type.kind == ValueKind::String {
                    Some(PineType::new(
                        strongest_qualifier(left_type.qualifier, right_type.qualifier),
                        ValueKind::String,
                    ))
                } else if is_numeric(left_type.kind) && is_numeric(right_type.kind) {
                    Some(PineType::new(
                        strongest_qualifier(left_type.qualifier, right_type.qualifier),
                        numeric_result_kind(op, left_type.kind, right_type.kind),
                    ))
                } else {
                    self.operator_error(
                        op,
                        "numeric or string operands",
                        left_type,
                        right_type,
                        span,
                    );
                    None
                }
            }
            BinaryOp::Sub | BinaryOp::Mul | BinaryOp::Div | BinaryOp::Mod => {
                if is_numeric(left_type.kind) && is_numeric(right_type.kind) {
                    Some(PineType::new(
                        strongest_qualifier(left_type.qualifier, right_type.qualifier),
                        numeric_result_kind(op, left_type.kind, right_type.kind),
                    ))
                } else {
                    self.operator_error(op, "numeric operands", left_type, right_type, span);
                    None
                }
            }
            BinaryOp::Eq | BinaryOp::NotEq => {
                if common_kind(left_type.kind, right_type.kind).is_some() {
                    Some(PineType::new(
                        strongest_qualifier(left_type.qualifier, right_type.qualifier),
                        ValueKind::Bool,
                    ))
                } else {
                    self.operator_error(op, "comparable operands", left_type, right_type, span);
                    None
                }
            }
            BinaryOp::Gt | BinaryOp::Gte | BinaryOp::Lt | BinaryOp::Lte => {
                if is_numeric(left_type.kind) && is_numeric(right_type.kind) {
                    Some(PineType::new(
                        strongest_qualifier(left_type.qualifier, right_type.qualifier),
                        ValueKind::Bool,
                    ))
                } else {
                    self.operator_error(op, "numeric operands", left_type, right_type, span);
                    None
                }
            }
            BinaryOp::And | BinaryOp::Or => {
                if left_type.kind == ValueKind::Bool && right_type.kind == ValueKind::Bool {
                    Some(PineType::new(
                        strongest_qualifier(left_type.qualifier, right_type.qualifier),
                        ValueKind::Bool,
                    ))
                } else {
                    self.operator_error(op, "bool operands", left_type, right_type, span);
                    None
                }
            }
        }
    }

    pub(crate) fn unary_operator_error(
        &mut self,
        op: UnaryOp,
        expected: &str,
        expr_type: PineType,
        span: Span,
    ) {
        self.diagnostics.push(Diagnostic::error(
            "E_OPERATOR_TYPE",
            format!(
                "operator `{}` expects {}, got {}",
                unary_operator_label(op),
                expected,
                pine_type_name(expr_type)
            ),
            span,
        ));
    }

    pub(crate) fn operator_error(
        &mut self,
        op: BinaryOp,
        expected: &str,
        left_type: PineType,
        right_type: PineType,
        span: Span,
    ) {
        self.diagnostics.push(Diagnostic::error(
            "E_OPERATOR_TYPE",
            format!(
                "operator `{}` expects {}, got {} and {}",
                binary_operator_label(op),
                expected,
                pine_type_name(left_type),
                pine_type_name(right_type)
            ),
            span,
        ));
    }

    pub(crate) fn expect_bool(&mut self, pine_type: PineType, span: Span) {
        if pine_type.kind == ValueKind::Bool {
            return;
        }
        if self.legacy.dialect() != PineDialect::V6
            && matches!(
                pine_type.kind,
                ValueKind::Int | ValueKind::Float | ValueKind::Na
            )
        {
            self.record_numeric_to_bool_coercion(span);
        } else {
            self.diagnostics.push(Diagnostic::error(
                "E_CONDITION_TYPE",
                format!("condition must be bool, got {}", pine_type_name(pine_type)),
                span,
            ));
        }
    }

    pub(crate) fn expect_int(&mut self, pine_type: PineType, span: Span) {
        if pine_type.kind != ValueKind::Int {
            self.diagnostics.push(Diagnostic::error(
                "E_LOOP_RANGE_TYPE",
                format!(
                    "for loop range must be int, got {}",
                    pine_type_name(pine_type)
                ),
                span,
            ));
        }
    }

    pub(crate) fn expect_non_zero_loop_step(&mut self, step: &Expr) {
        if self.known_const_int_value(step) == Some(0) {
            self.diagnostics.push(Diagnostic::error(
                "E_LOOP_STEP",
                "for loop step cannot be zero",
                step.span,
            ));
        }
    }

    pub(crate) fn merge_branch_types(
        &mut self,
        condition_type: PineType,
        then_type: PineType,
        else_type: PineType,
        condition_value: Option<bool>,
        span: Span,
    ) -> Option<PineType> {
        let Some(kind) = common_kind(then_type.kind, else_type.kind) else {
            self.diagnostics.push(Diagnostic::error(
                "E_BRANCH_TYPE",
                format!(
                    "ternary branches have incompatible types {} and {}",
                    value_kind_name(then_type.kind),
                    value_kind_name(else_type.kind)
                ),
                span,
            ));
            return None;
        };
        let branch_qualifier = match condition_value {
            Some(true) => then_type.qualifier,
            Some(false) => else_type.qualifier,
            None => strongest_qualifier(then_type.qualifier, else_type.qualifier),
        };

        Some(PineType::new(
            strongest_qualifier(condition_type.qualifier, branch_qualifier),
            kind,
        ))
    }
}

fn unary_operator_label(op: UnaryOp) -> &'static str {
    match op {
        UnaryOp::Plus => "+",
        UnaryOp::Minus => "-",
        UnaryOp::Not => "not",
    }
}

fn binary_operator_label(op: BinaryOp) -> &'static str {
    match op {
        BinaryOp::Add => "+",
        BinaryOp::Sub => "-",
        BinaryOp::Mul => "*",
        BinaryOp::Div => "/",
        BinaryOp::Mod => "%",
        BinaryOp::Eq => "==",
        BinaryOp::NotEq => "!=",
        BinaryOp::Gt => ">",
        BinaryOp::Gte => ">=",
        BinaryOp::Lt => "<",
        BinaryOp::Lte => "<=",
        BinaryOp::And => "and",
        BinaryOp::Or => "or",
    }
}
