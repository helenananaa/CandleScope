use crate::analyzer::maps::map_kind_from_template_name;
use crate::prelude::*;

mod helpers;

use helpers::*;

#[derive(Clone, Copy)]
struct TupleTypeContext<'a> {
    param_types: &'a HashMap<String, PineType>,
    param_user_types: &'a HashMap<String, String>,
    tuple_aliases: &'a HashMap<String, Vec<PineType>>,
}

impl Analyzer {
    pub(crate) fn type_of_expr_with_params(
        &self,
        expr: &Expr,
        param_types: &HashMap<String, PineType>,
    ) -> Option<PineType> {
        if let Some(pine_type) = self.expr_types.get(&self.expr_key(expr.span)) {
            return Some(*pine_type);
        }
        match &expr.kind {
            ExprKind::Literal(literal) => Some(literal_type(literal)),
            ExprKind::Identifier(name) => param_types
                .get(name)
                .copied()
                .or_else(|| {
                    self.bound_symbol(name, expr.span)
                        .map(|symbol| symbol.pine_type)
                })
                .or_else(|| self.scope.resolve(name).map(|symbol| symbol.pine_type)),
            ExprKind::QualifiedName(parts) => {
                if let Some(pine_type) =
                    self.type_of_bound_chart_point_field_access(parts, expr.span)
                {
                    return Some(pine_type);
                }
                if let Some(pine_type) = self.type_of_chart_point_field_access(parts) {
                    return Some(pine_type);
                }
                if let Some(pine_type) = self.type_of_bound_user_type_field_access(parts, expr.span)
                {
                    return Some(pine_type);
                }
                if let Some(pine_type) = self.type_of_user_type_field_access(parts) {
                    return Some(pine_type);
                }
                let name = expr_name(expr)?;
                pine_builtins::named_color(&name)
                    .map(|_| PineType::new(Qualifier::Const, ValueKind::Color))
                    .or_else(|| pine_builtins::builtin_series_value_type(&name))
                    .or_else(|| {
                        pine_builtins::named_float_constant(&name)
                            .map(|_| PineType::new(Qualifier::Const, ValueKind::Float))
                    })
                    .or_else(|| {
                        pine_builtins::named_int_constant(&name)
                            .map(|_| PineType::new(Qualifier::Const, ValueKind::Int))
                    })
                    .or_else(|| {
                        pine_builtins::named_string_constant(&name)
                            .map(|_| PineType::new(Qualifier::Const, ValueKind::String))
                    })
            }
            ExprKind::Unary { op, expr } => {
                self.type_of_expr_with_params(expr, param_types)
                    .map(|pine_type| {
                        PineType::new(
                            pine_type.qualifier,
                            if *op == UnaryOp::Not {
                                ValueKind::Bool
                            } else {
                                pine_type.kind
                            },
                        )
                    })
            }
            ExprKind::Binary { op, left, right } => {
                let left_type = self.type_of_expr_with_params(left, param_types)?;
                let right_type = self.type_of_expr_with_params(right, param_types)?;
                match op {
                    BinaryOp::Add
                        if left_type.kind == ValueKind::String
                            && right_type.kind == ValueKind::String =>
                    {
                        Some(PineType::new(
                            strongest_qualifier(left_type.qualifier, right_type.qualifier),
                            ValueKind::String,
                        ))
                    }
                    BinaryOp::Add
                    | BinaryOp::Sub
                    | BinaryOp::Mul
                    | BinaryOp::Div
                    | BinaryOp::Mod => Some(PineType::new(
                        strongest_qualifier(left_type.qualifier, right_type.qualifier),
                        numeric_result_kind(*op, left_type.kind, right_type.kind),
                    )),
                    BinaryOp::Eq
                    | BinaryOp::NotEq
                    | BinaryOp::Gt
                    | BinaryOp::Gte
                    | BinaryOp::Lt
                    | BinaryOp::Lte
                    | BinaryOp::And
                    | BinaryOp::Or => Some(PineType::new(
                        strongest_qualifier(left_type.qualifier, right_type.qualifier),
                        ValueKind::Bool,
                    )),
                }
            }
            ExprKind::Ternary {
                condition,
                then_expr,
                else_expr,
            } => {
                let condition_type = self.type_of_expr_with_params(condition, param_types)?;
                let then_type = self.type_of_expr_with_params(then_expr, param_types)?;
                let else_type = self.type_of_expr_with_params(else_expr, param_types)?;
                if let Some(condition_value) = self.known_const_bool_value(condition) {
                    return selected_branch_type(
                        condition_type.qualifier,
                        then_type,
                        else_type,
                        condition_value,
                    );
                }
                Some(PineType::new(
                    strongest_qualifier(
                        condition_type.qualifier,
                        strongest_qualifier(then_type.qualifier, else_type.qualifier),
                    ),
                    common_kind(then_type.kind, else_type.kind)?,
                ))
            }
            ExprKind::If {
                condition,
                then_branch,
                else_branch,
            } => self.type_of_if_expr_with_params(condition, then_branch, else_branch, param_types),
            ExprKind::Switch { selector, arms } => {
                self.type_of_switch_expr_with_params(selector.as_deref(), arms, param_types)
            }
            ExprKind::For {
                from,
                to,
                step,
                body,
                ..
            } => self.type_of_for_expr_with_params(from, to, step.as_deref(), body, param_types),
            ExprKind::ForIn { iterable, body, .. } => {
                self.type_of_for_in_expr_with_params(iterable, body, param_types)
            }
            ExprKind::While { condition, body } => {
                self.type_of_while_expr_with_params(condition, body, param_types)
            }
            ExprKind::Tuple(items) => {
                for item in items {
                    self.type_of_expr_with_params(item, param_types)?;
                }
                Some(pine_builtins::tuple_return_type())
            }
            ExprKind::Call { callee, args } => {
                let arg_types: Vec<_> = args
                    .iter()
                    .map(|arg| self.type_of_expr_with_params(&arg.value, param_types))
                    .collect();
                let name = expr_name(callee)?;
                if let Some((_, method_name)) = postfix_call_result_method_parts(callee, args)
                    && arg_types
                        .first()
                        .copied()
                        .flatten()
                        .is_some_and(|pine_type| is_array_kind(pine_type.kind))
                    && let Some(builtin_name) = array_call_result_builtin_name(method_name)
                    && let Some(signature) = pine_builtins::get_phase_1_builtin(builtin_name)
                {
                    return self.return_type_for_call(signature, args, &arg_types);
                }
                let matrix_method_name = builtin_matrix_call_result_method_name(callee, args)
                    .or_else(|| {
                        let (receiver_name, method_name) =
                            bound_matrix_call_result_method_parts(callee, args)?;
                        let receiver_type = param_types
                            .get(receiver_name)
                            .copied()
                            .or_else(|| {
                                self.bound_symbol(receiver_name, args.first()?.value.span)
                                    .map(|symbol| symbol.pine_type)
                            })
                            .or_else(|| {
                                self.scope
                                    .resolve(receiver_name)
                                    .map(|symbol| symbol.pine_type)
                            })?;
                        is_matrix_kind(receiver_type.kind).then_some(method_name)
                    })
                    .or_else(|| self.user_function_call_result_method_name(callee, args))
                    .or_else(|| self.user_method_call_result_method_name(callee, args))
                    .or_else(|| self.local_udf_call_result_method_name(callee, args));
                if let Some(method_name) = matrix_method_name
                    && arg_types
                        .first()
                        .copied()
                        .flatten()
                        .is_some_and(|pine_type| is_matrix_kind(pine_type.kind))
                    && let Some(builtin_name) = matrix_call_result_builtin_name(method_name)
                    && let Some(signature) = pine_builtins::get_phase_1_builtin(builtin_name)
                {
                    return self.return_type_for_call(signature, args, &arg_types);
                }
                if let Some(method_name) = builtin_map_call_result_method_name(callee, args)
                    .or_else(|| self.user_function_call_result_method_name(callee, args))
                    .or_else(|| self.user_method_call_result_method_name(callee, args))
                    && arg_types
                        .first()
                        .copied()
                        .flatten()
                        .is_some_and(|pine_type| pine_type.kind == ValueKind::Map)
                    && let Some(builtin_name) = map_call_result_builtin_name(method_name)
                {
                    return self.type_of_map_operation(builtin_name, args, param_types);
                }
                if let Some(pine_type) =
                    self.type_of_user_type_constructor_with_params(&name, args, param_types)
                {
                    Some(pine_type)
                } else if let Some(pine_type) = self
                    .type_of_imported_user_type_constructor_with_params(&name, args, param_types)
                {
                    Some(pine_type)
                } else if let Some((key_type, value_type)) = map_new_template_types(&name) {
                    map_kind_from_template_name(key_type)?;
                    map_kind_from_template_name(value_type)?;
                    Some(PineType::new(Qualifier::Simple, ValueKind::Map))
                } else if let Some(pine_type) = self.type_of_map_operation(&name, args, param_types)
                {
                    Some(pine_type)
                } else if let Some(signature) = pine_builtins::get_phase_1_builtin(&name) {
                    if is_ta_vwap_bands_call(&name, args) {
                        return Some(pine_builtins::tuple_return_type());
                    }
                    self.return_type_for_call(signature, args, &arg_types)
                } else if let Some((receiver_name, method_name)) = method_call_parts(callee) {
                    self.type_of_method_call_with_params(
                        receiver_name,
                        method_name,
                        callee.span,
                        args,
                        &arg_types,
                        param_types,
                    )
                } else {
                    let function = self.functions.get(&name)?;
                    let arg_indices = resolve_udf_arg_indices(&function.params, args).ok()?;
                    let mut nested_param_types = HashMap::new();
                    for (arg_type, param_index) in arg_types.into_iter().zip(arg_indices) {
                        let param = &function.params[param_index];
                        nested_param_types.insert(param.clone(), arg_type?);
                    }
                    self.with_source_context_ref(function.source_context_id, |analyzer| {
                        analyzer
                            .type_of_function_body_with_params(&function.body, &nested_param_types)
                    })
                }
            }
            ExprKind::History { expr, .. } => self
                .type_of_expr_with_params(expr, param_types)
                .map(|pine_type| PineType::new(Qualifier::Series, pine_type.kind)),
        }
    }

    pub(crate) fn type_of_method_call_with_params(
        &self,
        receiver_name: &str,
        method_name: &str,
        receiver_span: Span,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
        param_types: &HashMap<String, PineType>,
    ) -> Option<PineType> {
        let receiver_type = param_types
            .get(receiver_name)
            .copied()
            .or_else(|| {
                self.bound_symbol(receiver_name, receiver_span)
                    .map(|symbol| symbol.pine_type)
            })
            .or_else(|| {
                self.scope
                    .resolve(receiver_name)
                    .map(|symbol| symbol.pine_type)
            })?;
        let signature = if let Some(builtin_name) =
            drawing_method_builtin_name(receiver_type.kind, method_name)
        {
            pine_builtins::get_phase_1_builtin(&builtin_name)?
        } else if let Some(builtin_name) =
            matrix_method_builtin_name(receiver_type.kind, method_name)
        {
            pine_builtins::get_phase_1_builtin(builtin_name)?
        } else if receiver_type.kind == ValueKind::Map {
            let receiver_arg = receiver_call_arg(receiver_name, receiver_span);
            let builtin_name = map_method_builtin_name(method_name)?;
            return match builtin_name {
                "map.get" => {
                    let info = self.map_type_of_expr(&receiver_arg.value)?;
                    Some(PineType::new(Qualifier::Series, info.value_kind))
                }
                "map.contains" => Some(PineType::new(Qualifier::Series, ValueKind::Bool)),
                "map.put" | "map.clear" | "map.remove" | "map.put_all" => {
                    Some(PineType::new(Qualifier::Series, ValueKind::Void))
                }
                "map.copy" => Some(PineType::new(Qualifier::Simple, ValueKind::Map)),
                "map.size" => Some(PineType::new(Qualifier::Simple, ValueKind::Int)),
                "map.keys" => {
                    let info = self.map_type_of_expr(&receiver_arg.value)?;
                    let kind = info.key_kind.array_kind_from_element_kind()?;
                    Some(PineType::new(Qualifier::Simple, kind))
                }
                "map.values" => {
                    let info = self.map_type_of_expr(&receiver_arg.value)?;
                    let kind = info.value_kind.array_kind_from_element_kind()?;
                    Some(PineType::new(Qualifier::Simple, kind))
                }
                _ => None,
            };
        } else if is_array_kind(receiver_type.kind) {
            pine_builtins::get_phase_1_builtin(array_method_builtin_name(method_name)?)?
        } else {
            return None;
        };
        let mut method_arg_types = Vec::with_capacity(arg_types.len() + 1);
        method_arg_types.push(Some(receiver_type));
        method_arg_types.extend(arg_types.iter().copied());
        let receiver_arg = receiver_call_arg(receiver_name, receiver_span);
        let mut method_args = Vec::with_capacity(args.len() + 1);
        method_args.push(receiver_arg);
        method_args.extend(args.iter().cloned());
        self.return_type_for_call(signature, &method_args, &method_arg_types)
    }

    pub(crate) fn type_of_if_expr_with_params(
        &self,
        condition: &Expr,
        then_branch: &[Stmt],
        else_branch: &[Stmt],
        param_types: &HashMap<String, PineType>,
    ) -> Option<PineType> {
        let condition_type = self.type_of_expr_with_params(condition, param_types)?;
        let then_type = self.type_of_branch_return_with_params(then_branch, param_types)?;
        let else_type = self.type_of_branch_return_with_params(else_branch, param_types)?;
        if let Some(condition_value) = self.known_const_bool_value(condition) {
            return selected_branch_type(
                condition_type.qualifier,
                then_type,
                else_type,
                condition_value,
            );
        }
        Some(PineType::new(
            strongest_qualifier(
                condition_type.qualifier,
                strongest_qualifier(then_type.qualifier, else_type.qualifier),
            ),
            common_kind(then_type.kind, else_type.kind)?,
        ))
    }

    fn type_of_branch_return_with_params(
        &self,
        branch: &[Stmt],
        param_types: &HashMap<String, PineType>,
    ) -> Option<PineType> {
        let last = branch.last()?;
        match &last.kind {
            StmtKind::Expr(expr) => self.type_of_expr_with_params(expr, param_types),
            StmtKind::For {
                from,
                to,
                step,
                body,
                ..
            } => self.type_of_for_expr_with_params(from, to, step.as_ref(), body, param_types),
            StmtKind::ForIn { iterable, body, .. } => {
                self.type_of_for_in_expr_with_params(iterable, body, param_types)
            }
            StmtKind::While { condition, body } => {
                self.type_of_while_expr_with_params(condition, body, param_types)
            }
            _ => None,
        }
    }

    pub(crate) fn type_of_switch_expr_with_params(
        &self,
        selector: Option<&Expr>,
        arms: &[SwitchArm],
        param_types: &HashMap<String, PineType>,
    ) -> Option<PineType> {
        let selector_type = match selector {
            Some(selector) => Some(self.type_of_expr_with_params(selector, param_types)?),
            None => None,
        };
        let selector_key = selector.and_then(|selector| self.known_const_switch_key(selector));
        let selector_qualifier = selector_type.map_or(Qualifier::Const, |ty| ty.qualifier);
        let mut reachable_condition_qualifier = selector_qualifier;
        let mut result_type = None;
        let mut selected_result_type = None;
        let mut static_selection_open = selector.is_none() || selector_key.is_some();
        let mut dynamic_tail = selector.is_some() && selector_key.is_none();

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
            if let Some(condition) = &arm.condition {
                let condition_type = self.type_of_expr_with_params(condition, param_types)?;
                if arm_reachable {
                    reachable_condition_qualifier = strongest_qualifier(
                        reachable_condition_qualifier,
                        condition_type.qualifier,
                    );
                }
            }
            let arm_type = self.type_of_switch_arm_result_with_params(&arm.result, param_types)?;
            if static_selection_open && selected_result_type.is_none() {
                if selector.is_none() {
                    match (&arm.condition, condition_value) {
                        (Some(_), Some(true)) | (None, _) => {
                            selected_result_type = Some(arm_type);
                            static_selection_open = false;
                        }
                        (Some(_), Some(false)) => {}
                        (Some(_), None) => {
                            static_selection_open = false;
                            dynamic_tail = true;
                        }
                    }
                } else if let Some(selector_key) = selector_key.as_ref() {
                    match (&arm.condition, case_key.as_ref()) {
                        (Some(_), Some(case_key)) if case_key == selector_key => {
                            selected_result_type = Some(arm_type);
                            static_selection_open = false;
                        }
                        (Some(_), Some(_)) => {}
                        (Some(_), None) => {
                            static_selection_open = false;
                            dynamic_tail = true;
                        }
                        (None, _) => {
                            selected_result_type = Some(arm_type);
                            static_selection_open = false;
                        }
                    }
                }
            }
            result_type = Some(merge_result_types(result_type, arm_type)?);
        }

        result_type.map(|pine_type| {
            let branch_qualifier =
                selected_result_type.map_or(pine_type.qualifier, |ty: PineType| ty.qualifier);
            PineType::new(
                strongest_qualifier(reachable_condition_qualifier, branch_qualifier),
                pine_type.kind,
            )
        })
    }

    fn type_of_switch_arm_result_with_params(
        &self,
        result: &SwitchArmResult,
        param_types: &HashMap<String, PineType>,
    ) -> Option<PineType> {
        match result {
            SwitchArmResult::Expr(expr) => self.type_of_expr_with_params(expr, param_types),
            SwitchArmResult::Block(statements) => {
                self.type_of_branch_return_with_params(statements, param_types)
            }
        }
    }

    pub(crate) fn type_of_function_body_with_params(
        &self,
        body: &FunctionBody,
        param_types: &HashMap<String, PineType>,
    ) -> Option<PineType> {
        match body {
            FunctionBody::Expr(expr) => self.type_of_expr_with_params(expr, param_types),
            FunctionBody::Block(statements) => {
                let last = statements.last()?;
                match &last.kind {
                    StmtKind::Expr(expr) => self.type_of_expr_with_params(expr, param_types),
                    StmtKind::If {
                        condition,
                        then_branch,
                        else_branch,
                    } => self.type_of_function_if_return_with_params(
                        condition,
                        then_branch,
                        else_branch,
                        param_types,
                    ),
                    StmtKind::For {
                        from,
                        to,
                        step,
                        body,
                        ..
                    } => self.type_of_for_expr_with_params(
                        from,
                        to,
                        step.as_ref(),
                        body,
                        param_types,
                    ),
                    StmtKind::ForIn { iterable, body, .. } => {
                        self.type_of_for_in_expr_with_params(iterable, body, param_types)
                    }
                    StmtKind::While { condition, body } => {
                        self.type_of_while_expr_with_params(condition, body, param_types)
                    }
                    _ => None,
                }
            }
        }
    }

    fn type_of_for_expr_with_params(
        &self,
        from: &Expr,
        to: &Expr,
        step: Option<&Expr>,
        body: &[Stmt],
        param_types: &HashMap<String, PineType>,
    ) -> Option<PineType> {
        let loop_qualifier = self.loop_header_qualifier_with_params(from, to, step, param_types)?;
        let last = body.last()?;
        let body_type = self.type_of_loop_body_return_with_params(last, param_types)?;
        Some(PineType::new(
            strongest_qualifier(loop_qualifier, body_type.qualifier),
            body_type.kind,
        ))
    }

    fn type_of_function_if_return_with_params(
        &self,
        condition: &Expr,
        then_branch: &[Stmt],
        else_branch: &[Stmt],
        param_types: &HashMap<String, PineType>,
    ) -> Option<PineType> {
        let condition_type = self.type_of_expr_with_params(condition, param_types)?;
        let then_type =
            self.type_of_function_branch_return_with_params(then_branch, param_types)?;
        let else_type =
            self.type_of_function_branch_return_with_params(else_branch, param_types)?;
        if let Some(condition_value) = self.known_const_bool_value(condition) {
            return selected_branch_type(
                condition_type.qualifier,
                then_type,
                else_type,
                condition_value,
            );
        }
        Some(PineType::new(
            strongest_qualifier(
                condition_type.qualifier,
                strongest_qualifier(then_type.qualifier, else_type.qualifier),
            ),
            common_kind(then_type.kind, else_type.kind)?,
        ))
    }

    fn type_of_function_branch_return_with_params(
        &self,
        branch: &[Stmt],
        param_types: &HashMap<String, PineType>,
    ) -> Option<PineType> {
        let last = branch.last()?;
        match &last.kind {
            StmtKind::Expr(expr) => self.type_of_expr_with_params(expr, param_types),
            StmtKind::For {
                from,
                to,
                step,
                body,
                ..
            } => self.type_of_for_expr_with_params(from, to, step.as_ref(), body, param_types),
            StmtKind::ForIn { iterable, body, .. } => {
                self.type_of_for_in_expr_with_params(iterable, body, param_types)
            }
            StmtKind::While { condition, body } => {
                self.type_of_while_expr_with_params(condition, body, param_types)
            }
            _ => None,
        }
    }

    fn type_of_for_in_expr_with_params(
        &self,
        iterable: &Expr,
        body: &[Stmt],
        param_types: &HashMap<String, PineType>,
    ) -> Option<PineType> {
        let iterable_type = self.type_of_expr_with_params(iterable, param_types)?;
        let last = body.last()?;
        let body_type = self.type_of_loop_body_return_with_params(last, param_types)?;
        Some(PineType::new(
            strongest_qualifier(iterable_type.qualifier, body_type.qualifier),
            body_type.kind,
        ))
    }

    fn type_of_while_expr_with_params(
        &self,
        condition: &Expr,
        body: &[Stmt],
        param_types: &HashMap<String, PineType>,
    ) -> Option<PineType> {
        let condition_type = self.type_of_expr_with_params(condition, param_types)?;
        let last = body.last()?;
        let body_type = self.type_of_loop_body_return_with_params(last, param_types)?;
        Some(PineType::new(
            strongest_qualifier(condition_type.qualifier, body_type.qualifier),
            body_type.kind,
        ))
    }

    fn type_of_loop_body_return_with_params(
        &self,
        statement: &Stmt,
        param_types: &HashMap<String, PineType>,
    ) -> Option<PineType> {
        match &statement.kind {
            StmtKind::Expr(expr) => self.type_of_expr_with_params(expr, param_types),
            StmtKind::For {
                from,
                to,
                step,
                body,
                ..
            } => self.type_of_for_expr_with_params(from, to, step.as_ref(), body, param_types),
            StmtKind::ForIn { iterable, body, .. } => {
                self.type_of_for_in_expr_with_params(iterable, body, param_types)
            }
            StmtKind::While { condition, body } => {
                self.type_of_while_expr_with_params(condition, body, param_types)
            }
            _ => None,
        }
    }

    fn loop_header_qualifier_with_params(
        &self,
        from: &Expr,
        to: &Expr,
        step: Option<&Expr>,
        param_types: &HashMap<String, PineType>,
    ) -> Option<Qualifier> {
        let from_type = self.type_of_expr_with_params(from, param_types)?;
        let to_type = self.type_of_expr_with_params(to, param_types)?;
        let mut qualifier = strongest_qualifier(from_type.qualifier, to_type.qualifier);
        if let Some(step) = step {
            let step_type = self.type_of_expr_with_params(step, param_types)?;
            qualifier = strongest_qualifier(qualifier, step_type.qualifier);
        }
        Some(qualifier)
    }

    pub(crate) fn tuple_element_types(&self, expr: &Expr) -> Option<Vec<PineType>> {
        self.tuple_element_types_with_params(expr, &HashMap::new())
    }

    pub(crate) fn function_body_tuple_element_types(
        &self,
        body: &FunctionBody,
    ) -> Option<Vec<PineType>> {
        let param_types = HashMap::new();
        let param_user_types = HashMap::new();
        let tuple_aliases = HashMap::new();
        self.tuple_element_types_of_function_body_with_params(
            body,
            TupleTypeContext {
                param_types: &param_types,
                param_user_types: &param_user_types,
                tuple_aliases: &tuple_aliases,
            },
        )
    }

    fn tuple_element_types_with_params(
        &self,
        expr: &Expr,
        param_types: &HashMap<String, PineType>,
    ) -> Option<Vec<PineType>> {
        let param_user_types = HashMap::new();
        let tuple_aliases = HashMap::new();
        self.tuple_element_types_with_context(
            expr,
            TupleTypeContext {
                param_types,
                param_user_types: &param_user_types,
                tuple_aliases: &tuple_aliases,
            },
        )
    }

    fn tuple_element_types_with_context(
        &self,
        expr: &Expr,
        context: TupleTypeContext<'_>,
    ) -> Option<Vec<PineType>> {
        let tuple_alias_name = match &expr.kind {
            ExprKind::Identifier(name) => Some(name.as_str()),
            ExprKind::QualifiedName(parts) if parts.len() == 1 => Some(parts[0].as_str()),
            _ => None,
        };
        if let Some(name) = tuple_alias_name {
            if let Some(types) = context.tuple_aliases.get(name) {
                return Some(types.clone());
            }
            let symbol = self
                .bindings
                .get(&self.binding_key(name, expr.span))
                .copied()
                .or_else(|| self.scope.resolve(name))?;
            return self.symbol_tuple_element_types.get(&symbol.id).cloned();
        }
        match &expr.kind {
            ExprKind::Tuple(items) => items
                .iter()
                .map(|item| self.type_of_expr_with_params(item, context.param_types))
                .collect::<Option<_>>(),
            ExprKind::Ternary {
                condition,
                then_expr,
                else_expr,
            } => self.tuple_element_types_of_ternary_expr_with_params(
                condition, then_expr, else_expr, context,
            ),
            ExprKind::If {
                condition,
                then_branch,
                else_branch,
            } => self.tuple_element_types_of_if_expr_with_params(
                condition,
                then_branch,
                else_branch,
                context,
            ),
            ExprKind::Call { callee, args } => {
                let source_name = expr_name(callee)?;
                let name = self
                    .legacy
                    .canonical_call_name(self.current_source_context_id(), callee.span)
                    .map_or(source_name, str::to_owned);
                if name == "request.security" && args.len() == 3 {
                    return self.tuple_element_types_with_context(&args[2].value, context);
                }
                if is_ta_vwap_bands_call(&name, args) {
                    let series_float = PineType::new(Qualifier::Series, ValueKind::Float);
                    return Some(vec![series_float, series_float, series_float]);
                }
                if let Some(signature) = pine_builtins::get_phase_1_builtin(&name) {
                    return match signature.returns {
                        ReturnSpec::Tuple(types) => Some(types.to_vec()),
                        _ => None,
                    };
                }
                if let Some(types) = self
                    .tuple_element_types_of_alias_qualified_user_method_call_with_params(
                        &name, args, context,
                    )
                {
                    return Some(types);
                }
                if let Some((receiver_name, method_name)) = method_call_parts(callee)
                    && let Some(types) = self.tuple_element_types_of_user_method_call_with_params(
                        receiver_name,
                        method_name,
                        callee.span,
                        args,
                        context,
                    )
                {
                    return Some(types);
                }
                let function = self.functions.get(&name)?;
                let arg_types: Vec<_> = args
                    .iter()
                    .map(|arg| self.type_of_expr_with_params(&arg.value, context.param_types))
                    .collect();
                let arg_indices = resolve_udf_arg_indices(&function.params, args).ok()?;
                let mut nested_param_types = HashMap::new();
                let mut nested_param_user_types = HashMap::new();
                let nested_tuple_aliases = HashMap::new();
                for ((arg, arg_type), param_index) in args.iter().zip(arg_types).zip(arg_indices) {
                    let param = &function.params[param_index];
                    nested_param_types.insert(param.clone(), arg_type?);
                    if let Some(type_name) =
                        self.user_type_name_of_expr_with_tuple_context(&arg.value, context)
                    {
                        nested_param_user_types.insert(param.clone(), type_name);
                    }
                }
                self.with_source_context_ref(function.source_context_id, |analyzer| {
                    analyzer.tuple_element_types_of_function_body_with_params(
                        &function.body,
                        TupleTypeContext {
                            param_types: &nested_param_types,
                            param_user_types: &nested_param_user_types,
                            tuple_aliases: &nested_tuple_aliases,
                        },
                    )
                })
            }
            ExprKind::For {
                counter,
                from,
                to,
                step,
                body,
            } => {
                let loop_qualifier = self.loop_header_qualifier_with_params(
                    from,
                    to,
                    step.as_deref(),
                    context.param_types,
                )?;
                let mut tuple_aliases = context.tuple_aliases.clone();
                tuple_aliases.remove(counter);
                let loop_context = TupleTypeContext {
                    param_types: context.param_types,
                    param_user_types: context.param_user_types,
                    tuple_aliases: &tuple_aliases,
                };
                let types = self.tuple_element_types_of_function_branch_return_with_params(
                    body,
                    loop_context,
                )?;
                Some(promote_tuple_element_qualifiers(types, loop_qualifier))
            }
            ExprKind::ForIn {
                index,
                value,
                iterable,
                body,
            } => {
                let iterable_type = self.type_of_expr_with_params(iterable, context.param_types)?;
                let mut tuple_aliases = context.tuple_aliases.clone();
                if let Some(index) = index {
                    tuple_aliases.remove(index);
                }
                tuple_aliases.remove(value);
                let loop_context = TupleTypeContext {
                    param_types: context.param_types,
                    param_user_types: context.param_user_types,
                    tuple_aliases: &tuple_aliases,
                };
                let types = self.tuple_element_types_of_function_branch_return_with_params(
                    body,
                    loop_context,
                )?;
                Some(promote_tuple_element_qualifiers(
                    types,
                    iterable_type.qualifier,
                ))
            }
            ExprKind::While { condition, body } => {
                let condition_type =
                    self.type_of_expr_with_params(condition, context.param_types)?;
                let types =
                    self.tuple_element_types_of_function_branch_return_with_params(body, context)?;
                Some(promote_tuple_element_qualifiers(
                    types,
                    condition_type.qualifier,
                ))
            }
            ExprKind::Switch { selector, arms } => {
                let selector_qualifier = selector
                    .as_deref()
                    .and_then(|selector| {
                        self.type_of_expr_with_params(selector, context.param_types)
                    })
                    .map_or(Qualifier::Const, |ty| ty.qualifier);
                let mut reachable_condition_qualifier = selector_qualifier;
                let selector_key = selector
                    .as_deref()
                    .and_then(|selector| self.known_const_switch_key(selector));
                let mut result_types: Option<Vec<PineType>> = None;
                let mut selected_result_types: Option<Vec<PineType>> = None;
                let mut static_selection_open = selector.is_none() || selector_key.is_some();
                let mut dynamic_tail = selector.is_some() && selector_key.is_none();
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
                    if let Some(condition) = &arm.condition {
                        let condition_type =
                            self.type_of_expr_with_params(condition, context.param_types)?;
                        if arm_reachable {
                            reachable_condition_qualifier = strongest_qualifier(
                                reachable_condition_qualifier,
                                condition_type.qualifier,
                            );
                        }
                    }
                    let arm_types =
                        self.tuple_element_types_of_switch_arm_result(&arm.result, context)?;
                    if static_selection_open && selected_result_types.is_none() {
                        if selector.is_none() {
                            match (&arm.condition, condition_value) {
                                (Some(_), Some(true)) | (None, _) => {
                                    selected_result_types = Some(arm_types.clone());
                                    static_selection_open = false;
                                }
                                (Some(_), Some(false)) => {}
                                (Some(_), None) => {
                                    static_selection_open = false;
                                    dynamic_tail = true;
                                }
                            }
                        } else if let Some(selector_key) = selector_key.as_ref() {
                            match (&arm.condition, case_key.as_ref()) {
                                (Some(_), Some(case_key)) if case_key == selector_key => {
                                    selected_result_types = Some(arm_types.clone());
                                    static_selection_open = false;
                                }
                                (Some(_), Some(_)) => {}
                                (Some(_), None) => {
                                    static_selection_open = false;
                                    dynamic_tail = true;
                                }
                                (None, _) => {
                                    selected_result_types = Some(arm_types.clone());
                                    static_selection_open = false;
                                }
                            }
                        }
                    }
                    result_types = Some(merge_tuple_element_types(result_types, arm_types)?);
                }
                result_types.map(|types| {
                    types
                        .into_iter()
                        .enumerate()
                        .map(|pine_type| {
                            let branch_qualifier = selected_result_types
                                .as_ref()
                                .and_then(|selected_types| selected_types.get(pine_type.0))
                                .map_or(pine_type.1.qualifier, |selected_type| {
                                    selected_type.qualifier
                                });
                            PineType::new(
                                strongest_qualifier(
                                    reachable_condition_qualifier,
                                    branch_qualifier,
                                ),
                                pine_type.1.kind,
                            )
                        })
                        .collect()
                })
            }
            _ => None,
        }
    }

    fn tuple_element_types_of_user_method_call_with_params(
        &self,
        receiver_name: &str,
        method_name: &str,
        receiver_span: Span,
        args: &[CallArg],
        context: TupleTypeContext<'_>,
    ) -> Option<Vec<PineType>> {
        let receiver_symbol = self
            .bound_symbol(receiver_name, receiver_span)
            .or_else(|| self.scope.resolve(receiver_name));
        let receiver_type_name = context
            .param_user_types
            .get(receiver_name)
            .cloned()
            .or_else(|| {
                receiver_symbol
                    .as_ref()
                    .and_then(|symbol| self.symbol_user_types.get(&symbol.id).cloned())
            })?;
        let receiver_type = context
            .param_types
            .get(receiver_name)
            .copied()
            .or_else(|| receiver_symbol.as_ref().map(|symbol| symbol.pine_type))?;
        self.tuple_element_types_of_known_user_method_call_with_params(
            receiver_type_name,
            receiver_type,
            method_name,
            args,
            context,
        )
    }

    fn tuple_element_types_of_alias_qualified_user_method_call_with_params(
        &self,
        name: &str,
        args: &[CallArg],
        context: TupleTypeContext<'_>,
    ) -> Option<Vec<PineType>> {
        let (alias, method_name) = alias_qualified_method_name(name)?;
        let receiver_arg = args.first()?;
        let ExprKind::Identifier(receiver_name) = &receiver_arg.value.kind else {
            return None;
        };
        let receiver_symbol = self
            .bound_symbol(receiver_name, receiver_arg.value.span)
            .or_else(|| self.scope.resolve(receiver_name));
        let receiver_type_name = context
            .param_user_types
            .get(receiver_name)
            .cloned()
            .or_else(|| {
                receiver_symbol
                    .as_ref()
                    .and_then(|symbol| self.symbol_user_types.get(&symbol.id).cloned())
            })?;
        if !receiver_type_name.starts_with(&format!("{alias}.")) {
            return None;
        }
        let receiver_type = context
            .param_types
            .get(receiver_name)
            .copied()
            .or_else(|| receiver_symbol.as_ref().map(|symbol| symbol.pine_type))?;
        self.tuple_element_types_of_known_user_method_call_with_params(
            receiver_type_name,
            receiver_type,
            method_name,
            &args[1..],
            context,
        )
    }

    fn tuple_element_types_of_known_user_method_call_with_params(
        &self,
        receiver_type_name: String,
        receiver_type: PineType,
        method_name: &str,
        args: &[CallArg],
        context: TupleTypeContext<'_>,
    ) -> Option<Vec<PineType>> {
        let method = self
            .methods
            .get(&(receiver_type_name, method_name.to_owned()))?;
        let param_names: Vec<_> = method
            .params
            .iter()
            .map(|param| param.name.clone())
            .collect();
        let arg_indices = resolve_udf_arg_indices(&param_names, args).ok()?;
        let mut nested_param_types = HashMap::new();
        let mut nested_param_user_types = HashMap::new();
        let nested_tuple_aliases = HashMap::new();
        nested_param_types.insert(method.receiver_name.clone(), receiver_type);
        nested_param_user_types.insert(method.receiver_name.clone(), method.receiver_type.clone());
        let mut resolved_arg_types = vec![None; method.params.len()];
        let mut resolved_arg_user_types = vec![None; method.params.len()];
        for (arg, param_index) in args.iter().zip(arg_indices) {
            resolved_arg_types[param_index] =
                self.type_of_expr_with_params(&arg.value, context.param_types);
            resolved_arg_user_types[param_index] =
                self.user_type_name_of_expr_with_tuple_context(&arg.value, context);
        }
        for (param, (arg_type, arg_user_type)) in method
            .params
            .iter()
            .zip(resolved_arg_types.into_iter().zip(resolved_arg_user_types))
        {
            nested_param_types.insert(param.name.clone(), arg_type?);
            if let Some(type_name) = arg_user_type {
                nested_param_user_types.insert(param.name.clone(), type_name);
            }
        }
        self.with_source_context_ref(method.source_context_id, |analyzer| {
            analyzer.tuple_element_types_of_function_body_with_params(
                &method.body,
                TupleTypeContext {
                    param_types: &nested_param_types,
                    param_user_types: &nested_param_user_types,
                    tuple_aliases: &nested_tuple_aliases,
                },
            )
        })
    }

    fn user_type_name_of_expr_with_tuple_context(
        &self,
        expr: &Expr,
        context: TupleTypeContext<'_>,
    ) -> Option<String> {
        if let Some(type_name) = self.expr_user_type_name(expr) {
            return Some(type_name);
        }
        match &expr.kind {
            ExprKind::Identifier(name) => context
                .param_user_types
                .get(name)
                .cloned()
                .or_else(|| {
                    self.bound_symbol(name, expr.span)
                        .and_then(|symbol| self.symbol_user_types.get(&symbol.id).cloned())
                })
                .or_else(|| {
                    self.scope
                        .resolve(name)
                        .and_then(|symbol| self.symbol_user_types.get(&symbol.id).cloned())
                }),
            ExprKind::QualifiedName(parts) if parts.len() == 1 => {
                let name = &parts[0];
                context
                    .param_user_types
                    .get(name)
                    .cloned()
                    .or_else(|| {
                        self.bound_symbol(name, expr.span)
                            .and_then(|symbol| self.symbol_user_types.get(&symbol.id).cloned())
                    })
                    .or_else(|| {
                        self.scope
                            .resolve(name)
                            .and_then(|symbol| self.symbol_user_types.get(&symbol.id).cloned())
                    })
            }
            _ => self.user_type_name_of_expr(expr),
        }
    }

    fn tuple_element_types_of_ternary_expr_with_params(
        &self,
        condition: &Expr,
        then_expr: &Expr,
        else_expr: &Expr,
        context: TupleTypeContext<'_>,
    ) -> Option<Vec<PineType>> {
        let condition_type = self.type_of_expr_with_params(condition, context.param_types)?;
        let then_types = self.tuple_element_types_with_context(then_expr, context)?;
        let else_types = self.tuple_element_types_with_context(else_expr, context)?;
        if let Some(condition_value) = self.known_const_bool_value(condition) {
            return selected_tuple_branch_types(
                condition_type.qualifier,
                then_types,
                else_types,
                condition_value,
            );
        }
        let types = merge_tuple_element_types(Some(then_types), else_types)?;
        Some(promote_tuple_element_qualifiers(
            types,
            condition_type.qualifier,
        ))
    }

    fn tuple_element_types_of_if_expr_with_params(
        &self,
        condition: &Expr,
        then_branch: &[Stmt],
        else_branch: &[Stmt],
        context: TupleTypeContext<'_>,
    ) -> Option<Vec<PineType>> {
        let condition_type = self.type_of_expr_with_params(condition, context.param_types)?;
        let then_types =
            self.tuple_element_types_of_function_branch_return_with_params(then_branch, context)?;
        let else_types =
            self.tuple_element_types_of_function_branch_return_with_params(else_branch, context)?;
        if let Some(condition_value) = self.known_const_bool_value(condition) {
            return selected_tuple_branch_types(
                condition_type.qualifier,
                then_types,
                else_types,
                condition_value,
            );
        }
        let types = merge_tuple_element_types(Some(then_types), else_types)?;
        Some(promote_tuple_element_qualifiers(
            types,
            condition_type.qualifier,
        ))
    }

    fn tuple_element_types_of_function_body_with_params(
        &self,
        body: &FunctionBody,
        context: TupleTypeContext<'_>,
    ) -> Option<Vec<PineType>> {
        match body {
            FunctionBody::Expr(expr) => self.tuple_element_types_with_context(expr, context),
            FunctionBody::Block(statements) => {
                self.tuple_element_types_of_function_branch_return_with_params(statements, context)
            }
        }
    }

    fn tuple_element_types_of_function_if_return_with_params(
        &self,
        condition: &Expr,
        then_branch: &[Stmt],
        else_branch: &[Stmt],
        context: TupleTypeContext<'_>,
    ) -> Option<Vec<PineType>> {
        let condition_type = self.type_of_expr_with_params(condition, context.param_types)?;
        let then_types =
            self.tuple_element_types_of_function_branch_return_with_params(then_branch, context)?;
        let else_types =
            self.tuple_element_types_of_function_branch_return_with_params(else_branch, context)?;
        if let Some(condition_value) = self.known_const_bool_value(condition) {
            return selected_tuple_branch_types(
                condition_type.qualifier,
                then_types,
                else_types,
                condition_value,
            );
        }
        let types = merge_tuple_element_types(Some(then_types), else_types)?;
        Some(promote_tuple_element_qualifiers(
            types,
            condition_type.qualifier,
        ))
    }

    fn tuple_element_types_of_function_branch_return_with_params(
        &self,
        branch: &[Stmt],
        context: TupleTypeContext<'_>,
    ) -> Option<Vec<PineType>> {
        let (last, prefix) = branch.split_last()?;
        let mut tuple_aliases = context.tuple_aliases.clone();
        for statement in prefix {
            let nested_context = TupleTypeContext {
                param_types: context.param_types,
                param_user_types: context.param_user_types,
                tuple_aliases: &tuple_aliases,
            };
            match &statement.kind {
                StmtKind::Decl { name, value, .. } => {
                    if let Some(types) =
                        self.tuple_element_types_with_context(value, nested_context)
                    {
                        tuple_aliases.insert(name.clone(), types);
                    } else {
                        tuple_aliases.remove(name);
                    }
                }
                StmtKind::Reassign { name, value } if tuple_aliases.contains_key(name) => {
                    let types = self
                        .tuple_element_types_with_context(value, nested_context)
                        .unwrap_or_default();
                    tuple_aliases.insert(name.clone(), types);
                }
                StmtKind::TupleDecl { names, .. } => {
                    for name in names {
                        tuple_aliases.remove(name);
                    }
                }
                _ => {}
            }
        }
        let nested_context = TupleTypeContext {
            param_types: context.param_types,
            param_user_types: context.param_user_types,
            tuple_aliases: &tuple_aliases,
        };
        match &last.kind {
            StmtKind::If {
                condition,
                then_branch,
                else_branch,
            } => self.tuple_element_types_of_function_if_return_with_params(
                condition,
                then_branch,
                else_branch,
                nested_context,
            ),
            _ => self.tuple_element_types_of_loop_body_return_with_params(last, nested_context),
        }
    }

    fn tuple_element_types_of_loop_body_return_with_params(
        &self,
        statement: &Stmt,
        context: TupleTypeContext<'_>,
    ) -> Option<Vec<PineType>> {
        match &statement.kind {
            StmtKind::Expr(expr) => self.tuple_element_types_with_context(expr, context),
            StmtKind::For {
                counter,
                from,
                to,
                step,
                body,
            } => {
                let loop_qualifier = self.loop_header_qualifier_with_params(
                    from,
                    to,
                    step.as_ref(),
                    context.param_types,
                )?;
                let mut tuple_aliases = context.tuple_aliases.clone();
                tuple_aliases.remove(counter);
                let loop_context = TupleTypeContext {
                    param_types: context.param_types,
                    param_user_types: context.param_user_types,
                    tuple_aliases: &tuple_aliases,
                };
                let types = self.tuple_element_types_of_function_branch_return_with_params(
                    body,
                    loop_context,
                )?;
                Some(promote_tuple_element_qualifiers(types, loop_qualifier))
            }
            StmtKind::ForIn {
                index,
                value,
                iterable,
                body,
            } => {
                let iterable_type = self.type_of_expr_with_params(iterable, context.param_types)?;
                let mut tuple_aliases = context.tuple_aliases.clone();
                if let Some(index) = index {
                    tuple_aliases.remove(index);
                }
                tuple_aliases.remove(value);
                let loop_context = TupleTypeContext {
                    param_types: context.param_types,
                    param_user_types: context.param_user_types,
                    tuple_aliases: &tuple_aliases,
                };
                let types = self.tuple_element_types_of_function_branch_return_with_params(
                    body,
                    loop_context,
                )?;
                Some(promote_tuple_element_qualifiers(
                    types,
                    iterable_type.qualifier,
                ))
            }
            StmtKind::While { condition, body } => {
                let condition_type =
                    self.type_of_expr_with_params(condition, context.param_types)?;
                let types =
                    self.tuple_element_types_of_function_branch_return_with_params(body, context)?;
                Some(promote_tuple_element_qualifiers(
                    types,
                    condition_type.qualifier,
                ))
            }
            _ => None,
        }
    }

    fn tuple_element_types_of_switch_arm_result(
        &self,
        result: &SwitchArmResult,
        context: TupleTypeContext<'_>,
    ) -> Option<Vec<PineType>> {
        match result {
            SwitchArmResult::Expr(expr) => self.tuple_element_types_with_context(expr, context),
            SwitchArmResult::Block(statements) => {
                self.tuple_element_types_of_function_branch_return_with_params(statements, context)
            }
        }
    }

    fn type_of_map_operation(
        &self,
        name: &str,
        args: &[CallArg],
        param_types: &HashMap<String, PineType>,
    ) -> Option<PineType> {
        match name {
            "map.put" | "map.clear" | "map.remove" | "map.put_all" => {
                Some(PineType::new(Qualifier::Series, ValueKind::Void))
            }
            "map.contains" => Some(PineType::new(Qualifier::Series, ValueKind::Bool)),
            "map.copy" => Some(PineType::new(Qualifier::Simple, ValueKind::Map)),
            "map.size" => Some(PineType::new(Qualifier::Simple, ValueKind::Int)),
            "map.keys" | "map.values" => {
                let first_arg = args.first()?;
                let info = self.map_type_of_expr(&first_arg.value)?;
                let element_kind = if name == "map.keys" {
                    info.key_kind
                } else {
                    info.value_kind
                };
                Some(PineType::new(
                    Qualifier::Simple,
                    element_kind.array_kind_from_element_kind()?,
                ))
            }
            "map.get" => {
                let first_arg = args.first()?;
                let info = self.map_type_of_expr(&first_arg.value).or_else(|| {
                    let ExprKind::Identifier(name) = &first_arg.value.kind else {
                        return None;
                    };
                    param_types
                        .get(name)
                        .filter(|pine_type| pine_type.kind == ValueKind::Map)?;
                    None
                })?;
                Some(PineType::new(Qualifier::Series, info.value_kind))
            }
            _ => None,
        }
    }
}
