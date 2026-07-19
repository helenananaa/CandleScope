use crate::source_graph::SourceContextId;

use super::*;

pub(super) struct LoweredUserTypeCall {
    pub(super) key: String,
    pub(super) source_context_id: SourceContextId,
    pub(super) body: FunctionBody,
    pub(super) array_aliases: HashMap<String, UserTypeArrayIdentityResult>,
    pub(super) user_type_aliases: HashMap<String, UserTypeArrayIdentityResult>,
}

pub(super) enum LoweredUserTypeCallResolution {
    Resolved(Box<LoweredUserTypeCall>),
    Unresolved,
}

impl Analyzer {
    pub(super) fn user_type_name_of_expr_with_params(
        &self,
        expr: &Expr,
        param_exprs: &HashMap<String, HirExpr>,
    ) -> Option<String> {
        match self.user_type_result_with_params_and_aliases(
            expr,
            param_exprs,
            &HashMap::new(),
            &HashMap::new(),
            &mut Vec::new(),
        ) {
            UserTypeArrayIdentityResult::Known(type_name) => Some(type_name),
            UserTypeArrayIdentityResult::Na | UserTypeArrayIdentityResult::Unknown => None,
        }
    }

    pub(super) fn user_type_array_name_of_expr_with_params(
        &self,
        expr: &Expr,
        param_exprs: &HashMap<String, HirExpr>,
    ) -> Option<String> {
        match self.user_type_array_result_with_params_and_aliases(
            expr,
            param_exprs,
            &HashMap::new(),
            &HashMap::new(),
            &mut Vec::new(),
        ) {
            UserTypeArrayIdentityResult::Known(type_name) => Some(type_name),
            UserTypeArrayIdentityResult::Na | UserTypeArrayIdentityResult::Unknown => None,
        }
    }

    pub(super) fn user_type_array_result_with_params_and_aliases(
        &self,
        expr: &Expr,
        param_exprs: &HashMap<String, HirExpr>,
        array_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        user_type_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        call_stack: &mut Vec<String>,
    ) -> UserTypeArrayIdentityResult {
        let identifier_name = match &expr.kind {
            ExprKind::Identifier(name) => Some(name),
            ExprKind::QualifiedName(parts) if parts.len() == 1 => Some(&parts[0]),
            _ => None,
        };
        if let Some(name) = identifier_name {
            if name == "na" {
                return UserTypeArrayIdentityResult::Na;
            }
            if let Some(result) = array_aliases.get(name) {
                return result.clone();
            }
            if let Some(HirExpr {
                kind: HirExprKind::Symbol(symbol_id),
                ..
            }) = param_exprs.get(name)
                && let Some(type_name) = self.symbol_user_type_arrays.get(symbol_id)
            {
                return UserTypeArrayIdentityResult::Known(type_name.clone());
            }
            if let Some(symbol) = self.bound_symbol(name, expr.span)
                && let Some(type_name) = self.symbol_user_type_arrays.get(&symbol.id)
            {
                return UserTypeArrayIdentityResult::Known(type_name.clone());
            }
            if let Some(type_name) = self.user_type_array_name_of_expr(expr) {
                return UserTypeArrayIdentityResult::Known(type_name);
            }
            if self
                .bound_symbol(name, expr.span)
                .is_some_and(|symbol| symbol.pine_type.kind == ValueKind::Na)
            {
                return UserTypeArrayIdentityResult::Na;
            }
            return UserTypeArrayIdentityResult::Unknown;
        }

        match &expr.kind {
            ExprKind::History { expr, .. } => {
                return self.user_type_array_result_with_params_and_aliases(
                    expr,
                    param_exprs,
                    array_aliases,
                    user_type_aliases,
                    call_stack,
                );
            }
            ExprKind::Ternary {
                then_expr,
                else_expr,
                ..
            } => {
                return Self::merge_lowered_user_type_array_results([
                    self.user_type_array_result_with_params_and_aliases(
                        then_expr,
                        param_exprs,
                        array_aliases,
                        user_type_aliases,
                        call_stack,
                    ),
                    self.user_type_array_result_with_params_and_aliases(
                        else_expr,
                        param_exprs,
                        array_aliases,
                        user_type_aliases,
                        call_stack,
                    ),
                ]);
            }
            ExprKind::If {
                then_branch,
                else_branch,
                ..
            } => {
                return Self::merge_lowered_user_type_array_results([
                    self.user_type_array_branch_result_with_params_and_aliases(
                        then_branch,
                        param_exprs,
                        array_aliases,
                        user_type_aliases,
                        call_stack,
                    ),
                    self.user_type_array_branch_result_with_params_and_aliases(
                        else_branch,
                        param_exprs,
                        array_aliases,
                        user_type_aliases,
                        call_stack,
                    ),
                ]);
            }
            ExprKind::Switch { arms, .. } => {
                return Self::merge_lowered_user_type_array_results(arms.iter().map(|arm| {
                    self.user_type_array_switch_result_with_params_and_aliases(
                        &arm.result,
                        param_exprs,
                        array_aliases,
                        user_type_aliases,
                        call_stack,
                    )
                }));
            }
            ExprKind::ForIn {
                value,
                iterable,
                body,
                ..
            } => {
                let mut loop_user_type_aliases = user_type_aliases.clone();
                let element_result = self.user_type_array_result_with_params_and_aliases(
                    iterable,
                    param_exprs,
                    array_aliases,
                    user_type_aliases,
                    call_stack,
                );
                loop_user_type_aliases.insert(value.clone(), element_result);
                return self.user_type_array_branch_result_with_params_and_aliases(
                    body,
                    param_exprs,
                    array_aliases,
                    &loop_user_type_aliases,
                    call_stack,
                );
            }
            ExprKind::For { body, .. } | ExprKind::While { body, .. } => {
                return self.user_type_array_branch_result_with_params_and_aliases(
                    body,
                    param_exprs,
                    array_aliases,
                    user_type_aliases,
                    call_stack,
                );
            }
            ExprKind::Call { callee, args } => {
                if let Some((_, method_name)) = postfix_call_result_method_parts(callee, args)
                    && method_name == "copy"
                    && let Some(receiver) = args.first()
                {
                    let result = self.user_type_array_result_with_params_and_aliases(
                        &receiver.value,
                        param_exprs,
                        array_aliases,
                        user_type_aliases,
                        call_stack,
                    );
                    if !matches!(result, UserTypeArrayIdentityResult::Unknown) {
                        return result;
                    }
                }
                let Some(name) = expr_name(callee) else {
                    return UserTypeArrayIdentityResult::Unknown;
                };
                if let Some(type_name) = name
                    .strip_prefix("array.new<")
                    .and_then(|name| name.strip_suffix('>'))
                    && (self.user_types.contains_key(type_name)
                        || self.imported_user_type_array_is_supported(type_name))
                {
                    return UserTypeArrayIdentityResult::Known(type_name.to_owned());
                }
                if matches!(name.as_str(), "array.copy" | "array.slice" | "array.concat") {
                    return args
                        .first()
                        .map_or(UserTypeArrayIdentityResult::Unknown, |arg| {
                            self.user_type_array_result_with_params_and_aliases(
                                &arg.value,
                                param_exprs,
                                array_aliases,
                                user_type_aliases,
                                call_stack,
                            )
                        });
                }
                if name == "array.from" {
                    return Self::merge_lowered_user_type_array_results(args.iter().map(|arg| {
                        self.user_type_result_with_params_and_aliases(
                            &arg.value,
                            param_exprs,
                            array_aliases,
                            user_type_aliases,
                            call_stack,
                        )
                    }));
                }
                if let ExprKind::QualifiedName(parts) = &callee.kind
                    && let [receiver, method] = parts.as_slice()
                    && matches!(method.as_str(), "copy" | "slice" | "concat")
                {
                    let result = self.user_type_array_named_result_with_params_and_aliases(
                        receiver,
                        callee.span,
                        param_exprs,
                        array_aliases,
                    );
                    if !matches!(result, UserTypeArrayIdentityResult::Unknown) {
                        return result;
                    }
                }
                if let Some(call) = self.lowered_user_type_call(
                    callee,
                    args,
                    param_exprs,
                    array_aliases,
                    user_type_aliases,
                    call_stack,
                ) {
                    return match call {
                        LoweredUserTypeCallResolution::Resolved(call) => {
                            self.user_type_array_call_result(*call, call_stack)
                        }
                        LoweredUserTypeCallResolution::Unresolved => {
                            UserTypeArrayIdentityResult::Unknown
                        }
                    };
                }
            }
            _ => {}
        }

        self.user_type_array_name_of_expr(expr).map_or(
            UserTypeArrayIdentityResult::Unknown,
            UserTypeArrayIdentityResult::Known,
        )
    }

    fn user_type_array_named_result_with_params_and_aliases(
        &self,
        name: &str,
        span: Span,
        param_exprs: &HashMap<String, HirExpr>,
        aliases: &HashMap<String, UserTypeArrayIdentityResult>,
    ) -> UserTypeArrayIdentityResult {
        if let Some(result) = aliases.get(name) {
            return result.clone();
        }
        if let Some(HirExpr {
            kind: HirExprKind::Symbol(symbol_id),
            ..
        }) = param_exprs.get(name)
            && let Some(type_name) = self.symbol_user_type_arrays.get(symbol_id)
        {
            return UserTypeArrayIdentityResult::Known(type_name.clone());
        }
        let Some(symbol) = self
            .bound_symbol(name, span)
            .or_else(|| self.scope.resolve(name))
        else {
            return UserTypeArrayIdentityResult::Unknown;
        };
        self.symbol_user_type_arrays
            .get(&symbol.id)
            .map_or(UserTypeArrayIdentityResult::Unknown, |type_name| {
                UserTypeArrayIdentityResult::Known(type_name.clone())
            })
    }

    fn user_type_named_result_with_params_and_aliases(
        &self,
        name: &str,
        span: Span,
        param_exprs: &HashMap<String, HirExpr>,
        aliases: &HashMap<String, UserTypeArrayIdentityResult>,
    ) -> UserTypeArrayIdentityResult {
        if let Some(result) = aliases.get(name) {
            return result.clone();
        }
        if let Some(HirExpr {
            kind: HirExprKind::Symbol(symbol_id),
            ..
        }) = param_exprs.get(name)
            && let Some(type_name) = self.symbol_user_types.get(symbol_id)
        {
            return UserTypeArrayIdentityResult::Known(type_name.clone());
        }
        let Some(symbol) = self
            .bound_symbol(name, span)
            .or_else(|| self.scope.resolve(name))
        else {
            return UserTypeArrayIdentityResult::Unknown;
        };
        self.symbol_user_types
            .get(&symbol.id)
            .map_or(UserTypeArrayIdentityResult::Unknown, |type_name| {
                UserTypeArrayIdentityResult::Known(type_name.clone())
            })
    }

    pub(super) fn lowered_user_type_call(
        &self,
        callee: &Expr,
        args: &[CallArg],
        param_exprs: &HashMap<String, HirExpr>,
        array_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        user_type_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        call_stack: &mut Vec<String>,
    ) -> Option<LoweredUserTypeCallResolution> {
        let name = expr_name(callee)?;
        if let ExprKind::QualifiedName(parts) = &callee.kind
            && let [qualifier, method_name] = parts.as_slice()
        {
            if let Some(receiver_arg) = args.first()
                && let UserTypeArrayIdentityResult::Known(receiver_type) = self
                    .user_type_result_with_params_and_aliases(
                        &receiver_arg.value,
                        param_exprs,
                        array_aliases,
                        user_type_aliases,
                        call_stack,
                    )
                && (receiver_type == *qualifier
                    || receiver_type.starts_with(&format!("{qualifier}.")))
                && let Some(method) = self
                    .methods
                    .get(&(receiver_type.clone(), method_name.clone()))
                    .cloned()
            {
                return Some(
                    self.lowered_user_type_method_call(
                        receiver_type,
                        method_name,
                        method,
                        &args[1..],
                        param_exprs,
                        array_aliases,
                        user_type_aliases,
                        call_stack,
                    )
                    .map_or(LoweredUserTypeCallResolution::Unresolved, |call| {
                        LoweredUserTypeCallResolution::Resolved(Box::new(call))
                    }),
                );
            }

            if let UserTypeArrayIdentityResult::Known(receiver_type) = self
                .user_type_named_result_with_params_and_aliases(
                    qualifier,
                    callee.span,
                    param_exprs,
                    user_type_aliases,
                )
                && let Some(method) = self
                    .methods
                    .get(&(receiver_type.clone(), method_name.clone()))
                    .cloned()
            {
                return Some(
                    self.lowered_user_type_method_call(
                        receiver_type,
                        method_name,
                        method,
                        args,
                        param_exprs,
                        array_aliases,
                        user_type_aliases,
                        call_stack,
                    )
                    .map_or(LoweredUserTypeCallResolution::Unresolved, |call| {
                        LoweredUserTypeCallResolution::Resolved(Box::new(call))
                    }),
                );
            }
        }

        let function = self.functions.get(&name)?.clone();
        Some(
            self.lowered_user_type_function_call(
                name,
                function,
                args,
                param_exprs,
                array_aliases,
                user_type_aliases,
                call_stack,
            )
            .map_or(LoweredUserTypeCallResolution::Unresolved, |call| {
                LoweredUserTypeCallResolution::Resolved(Box::new(call))
            }),
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn lowered_user_type_function_call(
        &self,
        name: String,
        function: FunctionInfo,
        args: &[CallArg],
        param_exprs: &HashMap<String, HirExpr>,
        array_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        user_type_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        call_stack: &mut Vec<String>,
    ) -> Option<LoweredUserTypeCall> {
        let (array_aliases, user_type_aliases) = self.lowered_user_type_call_aliases(
            &function.params,
            args,
            param_exprs,
            array_aliases,
            user_type_aliases,
            call_stack,
        )?;
        Some(LoweredUserTypeCall {
            key: format!("function:{name}"),
            source_context_id: function.source_context_id,
            body: function.body,
            array_aliases,
            user_type_aliases,
        })
    }

    #[allow(clippy::too_many_arguments)]
    fn lowered_user_type_method_call(
        &self,
        receiver_type: String,
        method_name: &str,
        method: MethodInfo,
        args: &[CallArg],
        param_exprs: &HashMap<String, HirExpr>,
        array_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        user_type_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        call_stack: &mut Vec<String>,
    ) -> Option<LoweredUserTypeCall> {
        let param_names: Vec<_> = method
            .params
            .iter()
            .map(|param| param.name.clone())
            .collect();
        let (array_aliases, mut user_type_aliases) = self.lowered_user_type_call_aliases(
            &param_names,
            args,
            param_exprs,
            array_aliases,
            user_type_aliases,
            call_stack,
        )?;
        user_type_aliases.insert(
            method.receiver_name,
            UserTypeArrayIdentityResult::Known(receiver_type.clone()),
        );
        Some(LoweredUserTypeCall {
            key: format!("method:{receiver_type}.{method_name}"),
            source_context_id: method.source_context_id,
            body: method.body,
            array_aliases,
            user_type_aliases,
        })
    }

    #[allow(clippy::too_many_arguments)]
    fn lowered_user_type_call_aliases(
        &self,
        params: &[String],
        args: &[CallArg],
        param_exprs: &HashMap<String, HirExpr>,
        array_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        user_type_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        call_stack: &mut Vec<String>,
    ) -> Option<(
        HashMap<String, UserTypeArrayIdentityResult>,
        HashMap<String, UserTypeArrayIdentityResult>,
    )> {
        let arg_indices = resolve_udf_arg_indices(params, args).ok()?;
        let mut resolved_array_args = vec![UserTypeArrayIdentityResult::Unknown; params.len()];
        let mut resolved_user_type_args = vec![UserTypeArrayIdentityResult::Unknown; params.len()];
        for (arg, param_index) in args.iter().zip(arg_indices) {
            resolved_array_args[param_index] = self.user_type_array_result_with_params_and_aliases(
                &arg.value,
                param_exprs,
                array_aliases,
                user_type_aliases,
                call_stack,
            );
            resolved_user_type_args[param_index] = self.user_type_result_with_params_and_aliases(
                &arg.value,
                param_exprs,
                array_aliases,
                user_type_aliases,
                call_stack,
            );
        }
        Some((
            params.iter().cloned().zip(resolved_array_args).collect(),
            params
                .iter()
                .cloned()
                .zip(resolved_user_type_args)
                .collect(),
        ))
    }

    fn user_type_array_call_result(
        &self,
        call: LoweredUserTypeCall,
        call_stack: &mut Vec<String>,
    ) -> UserTypeArrayIdentityResult {
        if call_stack.len() >= MAX_FUNCTION_CALL_DEPTH || call_stack.contains(&call.key) {
            return UserTypeArrayIdentityResult::Unknown;
        }
        call_stack.push(call.key);
        let result =
            self.with_source_context_ref(call.source_context_id, |analyzer| match &call.body {
                FunctionBody::Expr(expr) => analyzer
                    .user_type_array_result_with_params_and_aliases(
                        expr,
                        &HashMap::new(),
                        &call.array_aliases,
                        &call.user_type_aliases,
                        call_stack,
                    ),
                FunctionBody::Block(statements) => analyzer
                    .user_type_array_branch_result_with_params_and_aliases(
                        statements,
                        &HashMap::new(),
                        &call.array_aliases,
                        &call.user_type_aliases,
                        call_stack,
                    ),
            });
        call_stack.pop();
        result
    }

    pub(super) fn declared_user_type_array_result(
        &self,
        declared_type: Option<&DeclaredType>,
        result: UserTypeArrayIdentityResult,
    ) -> UserTypeArrayIdentityResult {
        if matches!(result, UserTypeArrayIdentityResult::Known(_)) {
            return result;
        }
        let Some(DeclaredType::Array { element_type }) = declared_type else {
            return result;
        };
        if self.user_types.contains_key(element_type)
            || self.imported_user_type_array_is_supported(element_type)
        {
            UserTypeArrayIdentityResult::Known(element_type.clone())
        } else {
            result
        }
    }

    fn user_type_call_result(
        &self,
        call: LoweredUserTypeCall,
        call_stack: &mut Vec<String>,
    ) -> UserTypeArrayIdentityResult {
        if call_stack.len() >= MAX_FUNCTION_CALL_DEPTH || call_stack.contains(&call.key) {
            return UserTypeArrayIdentityResult::Unknown;
        }
        call_stack.push(call.key);
        let result =
            self.with_source_context_ref(call.source_context_id, |analyzer| match &call.body {
                FunctionBody::Expr(expr) => analyzer.user_type_result_with_params_and_aliases(
                    expr,
                    &HashMap::new(),
                    &call.array_aliases,
                    &call.user_type_aliases,
                    call_stack,
                ),
                FunctionBody::Block(statements) => analyzer
                    .user_type_branch_result_with_params_and_aliases(
                        statements,
                        &HashMap::new(),
                        &call.array_aliases,
                        &call.user_type_aliases,
                        call_stack,
                    ),
            });
        call_stack.pop();
        result
    }

    fn user_type_array_branch_result_with_params_and_aliases(
        &self,
        branch: &[Stmt],
        param_exprs: &HashMap<String, HirExpr>,
        outer_array_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        outer_user_type_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        call_stack: &mut Vec<String>,
    ) -> UserTypeArrayIdentityResult {
        self.user_type_array_branch_result_with_tuple_aliases(
            branch,
            param_exprs,
            outer_array_aliases,
            outer_user_type_aliases,
            &HashMap::new(),
            call_stack,
        )
    }

    fn user_type_array_branch_result_with_tuple_aliases(
        &self,
        branch: &[Stmt],
        param_exprs: &HashMap<String, HirExpr>,
        outer_array_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        outer_user_type_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        outer_tuple_aliases: &HashMap<String, Vec<UserTypeArrayIdentityResult>>,
        call_stack: &mut Vec<String>,
    ) -> UserTypeArrayIdentityResult {
        let Some((last, prefix)) = branch.split_last() else {
            return UserTypeArrayIdentityResult::Unknown;
        };
        let mut array_aliases = outer_array_aliases.clone();
        let mut user_type_aliases = outer_user_type_aliases.clone();
        let mut tuple_aliases = outer_tuple_aliases.clone();
        for statement in prefix {
            match &statement.kind {
                StmtKind::Decl {
                    declared_type,
                    name,
                    value,
                    ..
                } => {
                    let tuple_result = self.tuple_user_type_array_results_with_params_and_aliases(
                        value,
                        param_exprs,
                        &array_aliases,
                        &user_type_aliases,
                        &tuple_aliases,
                        call_stack,
                    );
                    if let Some(tuple_result) = tuple_result {
                        tuple_aliases.insert(name.clone(), tuple_result);
                    } else {
                        tuple_aliases.remove(name);
                    }
                    let result = self.declared_user_type_array_result(
                        declared_type.as_ref(),
                        self.user_type_array_result_with_params_and_aliases(
                            value,
                            param_exprs,
                            &array_aliases,
                            &user_type_aliases,
                            call_stack,
                        ),
                    );
                    array_aliases.insert(name.clone(), result);
                    let user_type_result = self.user_type_result_with_params_and_aliases(
                        value,
                        param_exprs,
                        &array_aliases,
                        &user_type_aliases,
                        call_stack,
                    );
                    user_type_aliases.insert(name.clone(), user_type_result);
                }
                StmtKind::Reassign { name, value } if tuple_aliases.contains_key(name) => {
                    let tuple_result = self.tuple_user_type_array_results_with_params_and_aliases(
                        value,
                        param_exprs,
                        &array_aliases,
                        &user_type_aliases,
                        &tuple_aliases,
                        call_stack,
                    );
                    if let Some(tuple_result) = tuple_result {
                        tuple_aliases.insert(name.clone(), tuple_result);
                    } else if let Some(previous) = tuple_aliases.get_mut(name) {
                        previous.fill(UserTypeArrayIdentityResult::Unknown);
                    }
                }
                StmtKind::TupleDecl { names, value } => {
                    for name in names {
                        tuple_aliases.remove(name);
                    }
                    if let Some(results) = self
                        .tuple_user_type_array_results_with_params_and_aliases(
                            value,
                            param_exprs,
                            &array_aliases,
                            &user_type_aliases,
                            &tuple_aliases,
                            call_stack,
                        )
                    {
                        array_aliases.extend(names.iter().cloned().zip(results));
                    }
                }
                _ => {}
            }
        }
        match &last.kind {
            StmtKind::Expr(expr) => self.user_type_array_result_with_params_and_aliases(
                expr,
                param_exprs,
                &array_aliases,
                &user_type_aliases,
                call_stack,
            ),
            StmtKind::If {
                then_branch,
                else_branch,
                ..
            } => Self::merge_lowered_user_type_array_results([
                self.user_type_array_branch_result_with_tuple_aliases(
                    then_branch,
                    param_exprs,
                    &array_aliases,
                    &user_type_aliases,
                    &tuple_aliases,
                    call_stack,
                ),
                self.user_type_array_branch_result_with_tuple_aliases(
                    else_branch,
                    param_exprs,
                    &array_aliases,
                    &user_type_aliases,
                    &tuple_aliases,
                    call_stack,
                ),
            ]),
            StmtKind::ForIn {
                index,
                value,
                iterable,
                body,
            } => {
                let mut loop_user_type_aliases = user_type_aliases.clone();
                let mut loop_tuple_aliases = tuple_aliases.clone();
                if let Some(index) = index {
                    loop_tuple_aliases.remove(index);
                }
                loop_tuple_aliases.remove(value);
                let element_result = self.user_type_array_result_with_params_and_aliases(
                    iterable,
                    param_exprs,
                    &array_aliases,
                    &user_type_aliases,
                    call_stack,
                );
                loop_user_type_aliases.insert(value.clone(), element_result);
                self.user_type_array_branch_result_with_tuple_aliases(
                    body,
                    param_exprs,
                    &array_aliases,
                    &loop_user_type_aliases,
                    &loop_tuple_aliases,
                    call_stack,
                )
            }
            StmtKind::For { counter, body, .. } => {
                let mut loop_tuple_aliases = tuple_aliases.clone();
                loop_tuple_aliases.remove(counter);
                self.user_type_array_branch_result_with_tuple_aliases(
                    body,
                    param_exprs,
                    &array_aliases,
                    &user_type_aliases,
                    &loop_tuple_aliases,
                    call_stack,
                )
            }
            StmtKind::While { body, .. } => self.user_type_array_branch_result_with_tuple_aliases(
                body,
                param_exprs,
                &array_aliases,
                &user_type_aliases,
                &tuple_aliases,
                call_stack,
            ),
            _ => UserTypeArrayIdentityResult::Unknown,
        }
    }

    fn user_type_array_switch_result_with_params_and_aliases(
        &self,
        result: &SwitchArmResult,
        param_exprs: &HashMap<String, HirExpr>,
        array_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        user_type_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        call_stack: &mut Vec<String>,
    ) -> UserTypeArrayIdentityResult {
        match result {
            SwitchArmResult::Expr(expr) => self.user_type_array_result_with_params_and_aliases(
                expr,
                param_exprs,
                array_aliases,
                user_type_aliases,
                call_stack,
            ),
            SwitchArmResult::Block(statements) => self
                .user_type_array_branch_result_with_params_and_aliases(
                    statements,
                    param_exprs,
                    array_aliases,
                    user_type_aliases,
                    call_stack,
                ),
        }
    }

    pub(super) fn merge_lowered_user_type_array_results(
        results: impl IntoIterator<Item = UserTypeArrayIdentityResult>,
    ) -> UserTypeArrayIdentityResult {
        let mut resolved = None;
        for result in results {
            match result {
                UserTypeArrayIdentityResult::Known(type_name)
                    if resolved
                        .as_ref()
                        .is_some_and(|resolved| resolved != &type_name) =>
                {
                    return UserTypeArrayIdentityResult::Unknown;
                }
                UserTypeArrayIdentityResult::Known(type_name) => {
                    resolved.get_or_insert(type_name);
                }
                UserTypeArrayIdentityResult::Na => {}
                UserTypeArrayIdentityResult::Unknown => {
                    return UserTypeArrayIdentityResult::Unknown;
                }
            }
        }
        resolved.map_or(
            UserTypeArrayIdentityResult::Na,
            UserTypeArrayIdentityResult::Known,
        )
    }

    pub(super) fn user_type_result_with_params_and_aliases(
        &self,
        expr: &Expr,
        param_exprs: &HashMap<String, HirExpr>,
        array_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        user_type_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        call_stack: &mut Vec<String>,
    ) -> UserTypeArrayIdentityResult {
        let identifier_name = match &expr.kind {
            ExprKind::Identifier(name) => Some(name),
            ExprKind::QualifiedName(parts) if parts.len() == 1 => Some(&parts[0]),
            _ => None,
        };
        if let Some(name) = identifier_name {
            if name == "na" {
                return UserTypeArrayIdentityResult::Na;
            }
            if let Some(result) = user_type_aliases.get(name) {
                return result.clone();
            }
            if let Some(HirExpr {
                kind: HirExprKind::Symbol(symbol_id),
                ..
            }) = param_exprs.get(name)
                && let Some(type_name) = self.symbol_user_types.get(symbol_id)
            {
                return UserTypeArrayIdentityResult::Known(type_name.clone());
            }
            if let Some(symbol) = self.bound_symbol(name, expr.span)
                && let Some(type_name) = self.symbol_user_types.get(&symbol.id)
            {
                return UserTypeArrayIdentityResult::Known(type_name.clone());
            }
            if let Some(type_name) = self.user_type_name_of_expr(expr) {
                return UserTypeArrayIdentityResult::Known(type_name);
            }
            if self
                .bound_symbol(name, expr.span)
                .is_some_and(|symbol| symbol.pine_type.kind == ValueKind::Na)
            {
                return UserTypeArrayIdentityResult::Na;
            }
            return UserTypeArrayIdentityResult::Unknown;
        }

        if let ExprKind::Call { callee, args } = &expr.kind
            && let Some(name) = expr_name(callee)
        {
            const ELEMENT_HELPERS: &[&str] = &["get", "pop", "remove", "shift", "first", "last"];
            if let Some((_, method_name)) = postfix_call_result_method_parts(callee, args)
                && matches!(method_name, "get" | "first" | "last")
                && let Some(receiver) = args.first()
                && let UserTypeArrayIdentityResult::Known(type_name) = self
                    .user_type_array_result_with_params_and_aliases(
                        &receiver.value,
                        param_exprs,
                        array_aliases,
                        user_type_aliases,
                        call_stack,
                    )
            {
                return UserTypeArrayIdentityResult::Known(type_name);
            }
            if let Some(helper) = name.strip_prefix("array.")
                && ELEMENT_HELPERS.contains(&helper)
                && let Some(array_arg) = args.first()
                && let UserTypeArrayIdentityResult::Known(type_name) = self
                    .user_type_array_result_with_params_and_aliases(
                        &array_arg.value,
                        param_exprs,
                        array_aliases,
                        user_type_aliases,
                        call_stack,
                    )
            {
                return UserTypeArrayIdentityResult::Known(type_name);
            }
            if let ExprKind::QualifiedName(parts) = &callee.kind
                && let [receiver, method] = parts.as_slice()
                && ELEMENT_HELPERS.contains(&method.as_str())
                && let UserTypeArrayIdentityResult::Known(type_name) = self
                    .user_type_array_named_result_with_params_and_aliases(
                        receiver,
                        callee.span,
                        param_exprs,
                        array_aliases,
                    )
            {
                return UserTypeArrayIdentityResult::Known(type_name);
            }
            if let Some(call) = self.lowered_user_type_call(
                callee,
                args,
                param_exprs,
                array_aliases,
                user_type_aliases,
                call_stack,
            ) {
                return match call {
                    LoweredUserTypeCallResolution::Resolved(call) => {
                        self.user_type_call_result(*call, call_stack)
                    }
                    LoweredUserTypeCallResolution::Unresolved => {
                        UserTypeArrayIdentityResult::Unknown
                    }
                };
            }
        }

        match &expr.kind {
            ExprKind::History { expr, .. } => {
                return self.user_type_result_with_params_and_aliases(
                    expr,
                    param_exprs,
                    array_aliases,
                    user_type_aliases,
                    call_stack,
                );
            }
            ExprKind::Ternary {
                then_expr,
                else_expr,
                ..
            } => {
                return Self::merge_lowered_user_type_array_results([
                    self.user_type_result_with_params_and_aliases(
                        then_expr,
                        param_exprs,
                        array_aliases,
                        user_type_aliases,
                        call_stack,
                    ),
                    self.user_type_result_with_params_and_aliases(
                        else_expr,
                        param_exprs,
                        array_aliases,
                        user_type_aliases,
                        call_stack,
                    ),
                ]);
            }
            ExprKind::If {
                then_branch,
                else_branch,
                ..
            } => {
                return Self::merge_lowered_user_type_array_results([
                    self.user_type_branch_result_with_params_and_aliases(
                        then_branch,
                        param_exprs,
                        array_aliases,
                        user_type_aliases,
                        call_stack,
                    ),
                    self.user_type_branch_result_with_params_and_aliases(
                        else_branch,
                        param_exprs,
                        array_aliases,
                        user_type_aliases,
                        call_stack,
                    ),
                ]);
            }
            ExprKind::Switch { arms, .. } => {
                return Self::merge_lowered_user_type_array_results(arms.iter().map(|arm| {
                    self.user_type_switch_result_with_params_and_aliases(
                        &arm.result,
                        param_exprs,
                        array_aliases,
                        user_type_aliases,
                        call_stack,
                    )
                }));
            }
            ExprKind::ForIn {
                value,
                iterable,
                body,
                ..
            } => {
                let mut loop_user_type_aliases = user_type_aliases.clone();
                let element_result = self.user_type_array_result_with_params_and_aliases(
                    iterable,
                    param_exprs,
                    array_aliases,
                    user_type_aliases,
                    call_stack,
                );
                loop_user_type_aliases.insert(value.clone(), element_result);
                return self.user_type_branch_result_with_params_and_aliases(
                    body,
                    param_exprs,
                    array_aliases,
                    &loop_user_type_aliases,
                    call_stack,
                );
            }
            ExprKind::For { body, .. } | ExprKind::While { body, .. } => {
                return self.user_type_branch_result_with_params_and_aliases(
                    body,
                    param_exprs,
                    array_aliases,
                    user_type_aliases,
                    call_stack,
                );
            }
            _ => {}
        }

        self.user_type_name_of_expr(expr).map_or(
            UserTypeArrayIdentityResult::Unknown,
            UserTypeArrayIdentityResult::Known,
        )
    }

    fn user_type_branch_result_with_params_and_aliases(
        &self,
        branch: &[Stmt],
        param_exprs: &HashMap<String, HirExpr>,
        outer_array_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        outer_user_type_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        call_stack: &mut Vec<String>,
    ) -> UserTypeArrayIdentityResult {
        let Some((last, prefix)) = branch.split_last() else {
            return UserTypeArrayIdentityResult::Unknown;
        };
        let mut array_aliases = outer_array_aliases.clone();
        let mut user_type_aliases = outer_user_type_aliases.clone();
        for statement in prefix {
            if let StmtKind::Decl { name, value, .. } = &statement.kind {
                let array_result = self.user_type_array_result_with_params_and_aliases(
                    value,
                    param_exprs,
                    &array_aliases,
                    &user_type_aliases,
                    call_stack,
                );
                array_aliases.insert(name.clone(), array_result);
                let result = self.user_type_result_with_params_and_aliases(
                    value,
                    param_exprs,
                    &array_aliases,
                    &user_type_aliases,
                    call_stack,
                );
                user_type_aliases.insert(name.clone(), result);
            }
        }
        match &last.kind {
            StmtKind::Expr(expr) => self.user_type_result_with_params_and_aliases(
                expr,
                param_exprs,
                &array_aliases,
                &user_type_aliases,
                call_stack,
            ),
            StmtKind::If {
                then_branch,
                else_branch,
                ..
            } => Self::merge_lowered_user_type_array_results([
                self.user_type_branch_result_with_params_and_aliases(
                    then_branch,
                    param_exprs,
                    &array_aliases,
                    &user_type_aliases,
                    call_stack,
                ),
                self.user_type_branch_result_with_params_and_aliases(
                    else_branch,
                    param_exprs,
                    &array_aliases,
                    &user_type_aliases,
                    call_stack,
                ),
            ]),
            StmtKind::ForIn {
                value,
                iterable,
                body,
                ..
            } => {
                let mut loop_user_type_aliases = user_type_aliases.clone();
                let element_result = self.user_type_array_result_with_params_and_aliases(
                    iterable,
                    param_exprs,
                    &array_aliases,
                    &user_type_aliases,
                    call_stack,
                );
                loop_user_type_aliases.insert(value.clone(), element_result);
                self.user_type_branch_result_with_params_and_aliases(
                    body,
                    param_exprs,
                    &array_aliases,
                    &loop_user_type_aliases,
                    call_stack,
                )
            }
            StmtKind::For { body, .. } | StmtKind::While { body, .. } => self
                .user_type_branch_result_with_params_and_aliases(
                    body,
                    param_exprs,
                    &array_aliases,
                    &user_type_aliases,
                    call_stack,
                ),
            _ => UserTypeArrayIdentityResult::Unknown,
        }
    }

    fn user_type_switch_result_with_params_and_aliases(
        &self,
        result: &SwitchArmResult,
        param_exprs: &HashMap<String, HirExpr>,
        array_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        user_type_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        call_stack: &mut Vec<String>,
    ) -> UserTypeArrayIdentityResult {
        match result {
            SwitchArmResult::Expr(expr) => self.user_type_result_with_params_and_aliases(
                expr,
                param_exprs,
                array_aliases,
                user_type_aliases,
                call_stack,
            ),
            SwitchArmResult::Block(statements) => self
                .user_type_branch_result_with_params_and_aliases(
                    statements,
                    param_exprs,
                    array_aliases,
                    user_type_aliases,
                    call_stack,
                ),
        }
    }
}
