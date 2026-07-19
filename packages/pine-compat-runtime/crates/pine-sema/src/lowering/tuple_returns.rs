use super::user_types::{LoweredUserTypeCall, LoweredUserTypeCallResolution};
use super::*;

impl Analyzer {
    pub(super) fn merge_tuple_user_type_array_result_vectors(
        results: impl IntoIterator<Item = Vec<UserTypeArrayIdentityResult>>,
    ) -> Option<Vec<UserTypeArrayIdentityResult>> {
        let mut merged: Option<Vec<UserTypeArrayIdentityResult>> = None;
        for next in results {
            let Some(current) = merged.take() else {
                merged = Some(next);
                continue;
            };
            if current.len() != next.len() {
                return None;
            }
            merged = Some(
                current
                    .into_iter()
                    .zip(next)
                    .map(|(current, next)| {
                        Self::merge_lowered_user_type_array_results([current, next])
                    })
                    .collect(),
            );
        }
        merged
    }

    pub(crate) fn tuple_user_type_array_results(
        &self,
        expr: &Expr,
    ) -> Option<Vec<UserTypeArrayIdentityResult>> {
        self.tuple_user_type_array_results_with_params_and_aliases(
            expr,
            &HashMap::new(),
            &HashMap::new(),
            &HashMap::new(),
            &HashMap::new(),
            &mut Vec::new(),
        )
    }

    pub(super) fn tuple_user_type_array_results_with_params(
        &self,
        expr: &Expr,
        param_exprs: &HashMap<String, HirExpr>,
    ) -> Option<Vec<UserTypeArrayIdentityResult>> {
        self.tuple_user_type_array_results_with_params_and_aliases(
            expr,
            param_exprs,
            &HashMap::new(),
            &HashMap::new(),
            &HashMap::new(),
            &mut Vec::new(),
        )
    }

    pub(crate) fn unresolved_function_body_user_type_array_tuple_slots(
        &self,
        body: &FunctionBody,
    ) -> Vec<usize> {
        let Some(element_types) = self.function_body_tuple_element_types(body) else {
            return Vec::new();
        };
        let results = match body {
            FunctionBody::Expr(expr) => self.tuple_user_type_array_results_with_params_and_aliases(
                expr,
                &HashMap::new(),
                &HashMap::new(),
                &HashMap::new(),
                &HashMap::new(),
                &mut Vec::new(),
            ),
            FunctionBody::Block(statements) => self
                .tuple_user_type_array_branch_results_with_params_and_aliases(
                    statements,
                    &HashMap::new(),
                    &HashMap::new(),
                    &HashMap::new(),
                    &HashMap::new(),
                    &mut Vec::new(),
                ),
        };
        element_types
            .iter()
            .enumerate()
            .filter_map(|(index, pine_type)| {
                (pine_type.kind == ValueKind::UserTypeArray
                    && !matches!(
                        results.as_ref().and_then(|results| results.get(index)),
                        Some(UserTypeArrayIdentityResult::Known(_))
                    ))
                .then_some(index)
            })
            .collect()
    }
    pub(super) fn tuple_user_type_array_results_with_params_and_aliases(
        &self,
        expr: &Expr,
        param_exprs: &HashMap<String, HirExpr>,
        array_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        user_type_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        tuple_aliases: &HashMap<String, Vec<UserTypeArrayIdentityResult>>,
        call_stack: &mut Vec<String>,
    ) -> Option<Vec<UserTypeArrayIdentityResult>> {
        let tuple_alias_name = match &expr.kind {
            ExprKind::Identifier(name) => Some(name.as_str()),
            ExprKind::QualifiedName(parts) if parts.len() == 1 => Some(parts[0].as_str()),
            _ => None,
        };
        if let Some(name) = tuple_alias_name {
            if let Some(result) = tuple_aliases.get(name) {
                return Some(result.clone());
            }
            if let Some(result) = self
                .bound_symbol(name, expr.span)
                .and_then(|symbol| self.symbol_tuple_user_type_arrays.get(&symbol.id))
            {
                return Some(result.clone());
            }
            let symbol = self
                .bindings
                .get(&self.binding_key(name, expr.span))
                .copied()
                .or_else(|| self.scope.resolve(name))?;
            return self.symbol_tuple_user_type_arrays.get(&symbol.id).cloned();
        }
        match &expr.kind {
            ExprKind::Tuple(items) => Some(
                items
                    .iter()
                    .map(|item| {
                        self.user_type_array_result_with_params_and_aliases(
                            item,
                            param_exprs,
                            array_aliases,
                            user_type_aliases,
                            call_stack,
                        )
                    })
                    .collect(),
            ),
            ExprKind::Ternary {
                then_expr,
                else_expr,
                ..
            } => Self::merge_tuple_user_type_array_result_vectors([
                self.tuple_user_type_array_results_with_params_and_aliases(
                    then_expr,
                    param_exprs,
                    array_aliases,
                    user_type_aliases,
                    tuple_aliases,
                    call_stack,
                )?,
                self.tuple_user_type_array_results_with_params_and_aliases(
                    else_expr,
                    param_exprs,
                    array_aliases,
                    user_type_aliases,
                    tuple_aliases,
                    call_stack,
                )?,
            ]),
            ExprKind::If {
                then_branch,
                else_branch,
                ..
            } => Self::merge_tuple_user_type_array_result_vectors([
                self.tuple_user_type_array_branch_results_with_params_and_aliases(
                    then_branch,
                    param_exprs,
                    array_aliases,
                    user_type_aliases,
                    tuple_aliases,
                    call_stack,
                )?,
                self.tuple_user_type_array_branch_results_with_params_and_aliases(
                    else_branch,
                    param_exprs,
                    array_aliases,
                    user_type_aliases,
                    tuple_aliases,
                    call_stack,
                )?,
            ]),
            ExprKind::Switch { arms, .. } => {
                let results = arms
                    .iter()
                    .map(|arm| {
                        self.tuple_user_type_array_switch_results_with_params_and_aliases(
                            &arm.result,
                            param_exprs,
                            array_aliases,
                            user_type_aliases,
                            tuple_aliases,
                            call_stack,
                        )
                    })
                    .collect::<Option<Vec<_>>>()?;
                Self::merge_tuple_user_type_array_result_vectors(results)
            }
            ExprKind::ForIn {
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
                    array_aliases,
                    user_type_aliases,
                    call_stack,
                );
                loop_user_type_aliases.insert(value.clone(), element_result);
                self.tuple_user_type_array_branch_results_with_params_and_aliases(
                    body,
                    param_exprs,
                    array_aliases,
                    &loop_user_type_aliases,
                    &loop_tuple_aliases,
                    call_stack,
                )
            }
            ExprKind::For { counter, body, .. } => {
                let mut loop_tuple_aliases = tuple_aliases.clone();
                loop_tuple_aliases.remove(counter);
                self.tuple_user_type_array_branch_results_with_params_and_aliases(
                    body,
                    param_exprs,
                    array_aliases,
                    user_type_aliases,
                    &loop_tuple_aliases,
                    call_stack,
                )
            }
            ExprKind::While { body, .. } => self
                .tuple_user_type_array_branch_results_with_params_and_aliases(
                    body,
                    param_exprs,
                    array_aliases,
                    user_type_aliases,
                    tuple_aliases,
                    call_stack,
                ),
            ExprKind::Call { callee, args } => {
                let call = self.lowered_user_type_call(
                    callee,
                    args,
                    param_exprs,
                    array_aliases,
                    user_type_aliases,
                    call_stack,
                )?;
                match call {
                    LoweredUserTypeCallResolution::Resolved(call) => {
                        self.tuple_user_type_array_call_result(*call, call_stack)
                    }
                    LoweredUserTypeCallResolution::Unresolved => None,
                }
            }
            _ => None,
        }
    }

    fn tuple_user_type_array_call_result(
        &self,
        call: LoweredUserTypeCall,
        call_stack: &mut Vec<String>,
    ) -> Option<Vec<UserTypeArrayIdentityResult>> {
        if call_stack.len() >= MAX_FUNCTION_CALL_DEPTH || call_stack.contains(&call.key) {
            return None;
        }
        call_stack.push(call.key);
        let result =
            self.with_source_context_ref(call.source_context_id, |analyzer| match &call.body {
                FunctionBody::Expr(expr) => analyzer
                    .tuple_user_type_array_results_with_params_and_aliases(
                        expr,
                        &HashMap::new(),
                        &call.array_aliases,
                        &call.user_type_aliases,
                        &HashMap::new(),
                        call_stack,
                    ),
                FunctionBody::Block(statements) => analyzer
                    .tuple_user_type_array_branch_results_with_params_and_aliases(
                        statements,
                        &HashMap::new(),
                        &call.array_aliases,
                        &call.user_type_aliases,
                        &HashMap::new(),
                        call_stack,
                    ),
            });
        call_stack.pop();
        result
    }

    pub(super) fn tuple_user_type_array_branch_results_with_params_and_aliases(
        &self,
        branch: &[Stmt],
        param_exprs: &HashMap<String, HirExpr>,
        outer_array_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        outer_user_type_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        outer_tuple_aliases: &HashMap<String, Vec<UserTypeArrayIdentityResult>>,
        call_stack: &mut Vec<String>,
    ) -> Option<Vec<UserTypeArrayIdentityResult>> {
        let (last, prefix) = branch.split_last()?;
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
            StmtKind::Expr(expr) => expr_name(expr)
                .and_then(|alias| tuple_aliases.get(&alias).cloned())
                .or_else(|| {
                    self.tuple_user_type_array_results_with_params_and_aliases(
                        expr,
                        param_exprs,
                        &array_aliases,
                        &user_type_aliases,
                        &tuple_aliases,
                        call_stack,
                    )
                }),
            StmtKind::If {
                then_branch,
                else_branch,
                ..
            } => Self::merge_tuple_user_type_array_result_vectors([
                self.tuple_user_type_array_branch_results_with_params_and_aliases(
                    then_branch,
                    param_exprs,
                    &array_aliases,
                    &user_type_aliases,
                    &tuple_aliases,
                    call_stack,
                )?,
                self.tuple_user_type_array_branch_results_with_params_and_aliases(
                    else_branch,
                    param_exprs,
                    &array_aliases,
                    &user_type_aliases,
                    &tuple_aliases,
                    call_stack,
                )?,
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
                self.tuple_user_type_array_branch_results_with_params_and_aliases(
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
                self.tuple_user_type_array_branch_results_with_params_and_aliases(
                    body,
                    param_exprs,
                    &array_aliases,
                    &user_type_aliases,
                    &loop_tuple_aliases,
                    call_stack,
                )
            }
            StmtKind::While { body, .. } => self
                .tuple_user_type_array_branch_results_with_params_and_aliases(
                    body,
                    param_exprs,
                    &array_aliases,
                    &user_type_aliases,
                    &tuple_aliases,
                    call_stack,
                ),
            _ => None,
        }
    }

    fn tuple_user_type_array_switch_results_with_params_and_aliases(
        &self,
        result: &SwitchArmResult,
        param_exprs: &HashMap<String, HirExpr>,
        array_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        user_type_aliases: &HashMap<String, UserTypeArrayIdentityResult>,
        tuple_aliases: &HashMap<String, Vec<UserTypeArrayIdentityResult>>,
        call_stack: &mut Vec<String>,
    ) -> Option<Vec<UserTypeArrayIdentityResult>> {
        match result {
            SwitchArmResult::Expr(expr) => self
                .tuple_user_type_array_results_with_params_and_aliases(
                    expr,
                    param_exprs,
                    array_aliases,
                    user_type_aliases,
                    tuple_aliases,
                    call_stack,
                ),
            SwitchArmResult::Block(statements) => self
                .tuple_user_type_array_branch_results_with_params_and_aliases(
                    statements,
                    param_exprs,
                    array_aliases,
                    user_type_aliases,
                    tuple_aliases,
                    call_stack,
                ),
        }
    }
}
