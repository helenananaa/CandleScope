use crate::prelude::*;

mod budget;
mod builtin_calls;
mod call_result_methods;
mod function_returns;
mod inline_calls;
mod literals;
mod pure_series;
mod reassignments;
mod tuple_returns;
pub(crate) mod user_types;

pub(crate) use literals::lower_literal;

pub(crate) fn prepend_block_statements(mut prefix: Vec<HirStmt>, expr: HirExpr) -> HirExpr {
    match expr.kind {
        HirExprKind::Block { statements, result } => {
            prefix.extend(statements);
            HirExpr {
                kind: HirExprKind::Block {
                    statements: prefix,
                    result,
                },
                pine_type: expr.pine_type,
                series_id: expr.series_id,
            }
        }
        _ => HirExpr {
            pine_type: expr.pine_type,
            series_id: expr.series_id,
            kind: HirExprKind::Block {
                statements: prefix,
                result: Box::new(expr),
            },
        },
    }
}

fn builtin_qualified_series_key(parts: &[String]) -> Option<String> {
    if parts.len() < 2 {
        return None;
    }
    let name = parts.join(".");
    let is_named_const = pine_builtins::named_color(&name).is_some()
        || pine_builtins::named_float_constant(&name).is_some()
        || pine_builtins::named_int_constant(&name).is_some()
        || pine_builtins::named_string_constant(&name).is_some();
    let is_stable_builtin_value =
        pine_builtins::builtin_series_value_type(&name).is_some_and(|pine_type| {
            pine_type.qualifier != Qualifier::Series
                || name.starts_with("barstate.")
                || name.starts_with("session.")
        });
    (is_named_const || is_stable_builtin_value).then(|| format!("builtin:{name}"))
}

fn pure_math_call_name(name: &str) -> bool {
    matches!(
        name,
        "math.abs"
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
    )
}

fn pure_math_variadic_call_name(name: &str) -> bool {
    matches!(name, "math.max" | "math.min" | "math.avg")
}

fn pure_fixed_builtin_call_name(name: &str) -> bool {
    matches!(
        name,
        "nz" | "fixnan"
            | "str.tonumber"
            | "str.length"
            | "str.pos"
            | "color.r"
            | "color.g"
            | "color.b"
            | "color.t"
    )
}

fn final_loop_statement_expr(statement: &Stmt) -> Option<Expr> {
    match &statement.kind {
        StmtKind::For {
            counter,
            from,
            to,
            step,
            body,
        } => Some(Expr {
            span: statement.span,
            kind: ExprKind::For {
                counter: counter.to_owned(),
                from: Box::new(from.clone()),
                to: Box::new(to.clone()),
                step: step.clone().map(Box::new),
                body: body.to_vec(),
            },
        }),
        StmtKind::ForIn {
            index,
            value,
            iterable,
            body,
        } => Some(Expr {
            span: statement.span,
            kind: ExprKind::ForIn {
                index: index.clone(),
                value: value.to_owned(),
                iterable: Box::new(iterable.clone()),
                body: body.to_vec(),
            },
        }),
        StmtKind::While { condition, body } => Some(Expr {
            span: statement.span,
            kind: ExprKind::While {
                condition: Box::new(condition.clone()),
                body: body.to_vec(),
            },
        }),
        _ => None,
    }
}

pub(crate) fn lower_unary_op(op: UnaryOp) -> HirUnaryOp {
    match op {
        UnaryOp::Plus => HirUnaryOp::Plus,
        UnaryOp::Minus => HirUnaryOp::Minus,
        UnaryOp::Not => HirUnaryOp::Not,
    }
}
pub(crate) fn lower_binary_op(op: BinaryOp) -> HirBinaryOp {
    match op {
        BinaryOp::Add => HirBinaryOp::Add,
        BinaryOp::Sub => HirBinaryOp::Sub,
        BinaryOp::Mul => HirBinaryOp::Mul,
        BinaryOp::Div => HirBinaryOp::Div,
        BinaryOp::Mod => HirBinaryOp::Mod,
        BinaryOp::Eq => HirBinaryOp::Eq,
        BinaryOp::NotEq => HirBinaryOp::NotEq,
        BinaryOp::Gt => HirBinaryOp::Gt,
        BinaryOp::Gte => HirBinaryOp::Gte,
        BinaryOp::Lt => HirBinaryOp::Lt,
        BinaryOp::Lte => HirBinaryOp::Lte,
        BinaryOp::And => HirBinaryOp::And,
        BinaryOp::Or => HirBinaryOp::Or,
    }
}
impl Analyzer {
    pub(crate) fn lower_program(&mut self, program: &Program) -> Option<HirProgram> {
        debug_assert!(self.source_context_stack_is_restored());
        self.lower_reassigned_symbols = self.collect_lower_reassigned_symbols(&program.statements);
        let mut statements = Vec::new();
        for statement in &program.statements {
            if matches!(
                statement.kind,
                StmtKind::Function { .. }
                    | StmtKind::Import(_)
                    | StmtKind::Library(_)
                    | StmtKind::Export(_)
                    | StmtKind::UserType(_)
                    | StmtKind::Method(_)
                    | StmtKind::Unsupported { .. }
            ) {
                continue;
            }
            statements.push(self.lower_stmt(statement)?);
        }
        if self.has_errors() {
            return None;
        }

        let symbols = self.lower_symbols();
        let history = infer_history_requirements(&statements, &symbols);
        let max_bars_back = infer_max_bars_back(&statements);
        let series_max_bars_back = infer_series_max_bars_back(&statements);
        let script_mode = self
            .script_declaration
            .map_or(ScriptMode::Indicator, |(mode, _)| mode);
        let program = HirProgram {
            language_version: program.version.map(|version| version.version),
            script_mode,
            strategy_settings: self.strategy_settings,
            drawing_settings: self.drawing_settings,
            user_types: self.lower_user_types(),
            symbols,
            statements,
            next_series_id: self.next_series_id,
            next_call_site_id: self.next_call_site_id,
            next_var_slot_id: self.next_var_slot_id,
            max_bars_back,
            series_max_bars_back,
            history: history.program,
            series_history: history.series,
        };
        debug_assert!(self.source_context_stack_is_restored());
        Some(program)
    }

    fn lower_user_types(&self) -> Vec<HirUserTypeInfo> {
        let mut local_user_types = self.user_types.values().collect::<Vec<_>>();
        local_user_types.sort_by(|left, right| left.name.cmp(&right.name));
        let mut imported_user_types = self.imported_user_types.iter().collect::<Vec<_>>();
        imported_user_types.sort_by(|left, right| left.0.cmp(right.0));

        let mut user_types = local_user_types
            .into_iter()
            .map(|user_type| {
                let type_name = user_type.name.clone();
                HirUserTypeInfo {
                    identity: HirUserTypeIdentity {
                        source_id: user_type.identity.source_id.get(),
                        type_name: type_name.clone(),
                    },
                    fields: user_type
                        .fields
                        .iter()
                        .map(|field| HirUserTypeField {
                            name: field.name.clone(),
                            user_type_name: field.user_type_name.clone(),
                        })
                        .collect(),
                }
            })
            .collect::<Vec<_>>();

        user_types.extend(
            imported_user_types
                .into_iter()
                .map(|(type_name, user_type)| HirUserTypeInfo {
                    identity: HirUserTypeIdentity {
                        source_id: user_type.identity.source_id.get(),
                        type_name: type_name.clone(),
                    },
                    fields: user_type
                        .fields
                        .iter()
                        .map(|field| HirUserTypeField {
                            name: field.name.clone(),
                            user_type_name: field.pine_type.is_none().then(|| {
                                self.imported_user_types
                                    .iter()
                                    .find(|(_, nested)| {
                                        nested.identity.source_id == user_type.identity.source_id
                                            && nested.identity.name == field.type_name
                                    })
                                    .map_or_else(
                                        || field.type_name.clone(),
                                        |(name, _)| name.clone(),
                                    )
                            }),
                        })
                        .collect(),
                }),
        );
        user_types
    }

    pub(crate) fn lower_symbols(&self) -> Vec<HirSymbol> {
        self.scope.lower_symbols()
    }

    fn lower_alias_decl_symbol_series_id(
        &mut self,
        name: &str,
        symbol: SymbolInfo,
        source_expr: &Expr,
        lowered_value: &HirExpr,
    ) -> SymbolInfo {
        if !self.lower_symbol_overrides.is_empty()
            || symbol.persistence != PersistenceKind::None
            || self.lower_reassigned_symbols.contains(&symbol.id)
            || lowered_value.pine_type.qualifier != Qualifier::Series
            || is_collection_kind(lowered_value.pine_type.kind)
            || lowered_value.pine_type.kind == ValueKind::Tuple
            || self.pure_expr_series_key(source_expr).is_none()
        {
            return symbol;
        }
        let Some(series_id) = lowered_value.series_id else {
            return symbol;
        };
        if symbol.series_id == Some(series_id) {
            return symbol;
        }

        let updated = SymbolInfo {
            series_id: Some(series_id),
            ..symbol
        };
        self.scope.update(name, updated);
        for binding in self.bindings.values_mut() {
            if binding.id == symbol.id {
                *binding = updated;
            }
        }
        updated
    }

    pub(crate) fn bind_symbol(&mut self, name: &str, span: Span, symbol: SymbolInfo) {
        let key = self.binding_key(name, span);
        self.bindings.insert(key, symbol);
    }

    pub(crate) fn bound_symbol(&self, name: &str, span: Span) -> Option<SymbolInfo> {
        let symbol = self.bindings.get(&self.binding_key(name, span)).copied()?;
        self.lower_symbol_overrides
            .iter()
            .rev()
            .find_map(|overrides| overrides.get(&symbol.id).copied())
            .or(Some(symbol))
    }

    pub(crate) fn has_lower_symbol_override(&self, symbol_id: SymbolId) -> bool {
        self.lower_symbol_overrides
            .iter()
            .rev()
            .any(|overrides| overrides.contains_key(&symbol_id))
    }

    pub(crate) fn lower_decl_symbol(&mut self, name: &str, span: Span) -> Option<SymbolInfo> {
        let symbol = self.bindings.get(&self.binding_key(name, span)).copied()?;
        if self.lower_symbol_overrides.is_empty() || self.scope.contains_lower_symbol(symbol.id) {
            return Some(symbol);
        }
        if let Some(existing) = self
            .lower_symbol_overrides
            .iter()
            .rev()
            .find_map(|overrides| overrides.get(&symbol.id).copied())
        {
            return Some(existing);
        }
        let fresh = self.fresh_lower_symbol(name, symbol);
        self.lower_symbol_overrides
            .last_mut()
            .expect("override scope is active")
            .insert(symbol.id, fresh);
        Some(fresh)
    }

    pub(crate) fn lower_stmt(&mut self, statement: &pine_syntax::Stmt) -> Option<HirStmt> {
        self.lower_stmt_with_params(statement, &HashMap::new(), &HashMap::new())
    }

    pub(crate) fn lower_stmt_with_params(
        &mut self,
        statement: &pine_syntax::Stmt,
        param_exprs: &HashMap<String, HirExpr>,
        param_types: &HashMap<String, PineType>,
    ) -> Option<HirStmt> {
        if !self.record_lowering_node(statement.span) {
            return None;
        }

        let kind = match &statement.kind {
            StmtKind::Expr(expr) => match &expr.kind {
                ExprKind::Switch { selector, arms } => HirStmtKind::Switch {
                    selector: match selector {
                        Some(selector) => {
                            Some(self.lower_expr_with_params(selector, param_exprs, param_types)?)
                        }
                        None => None,
                    },
                    arms: arms
                        .iter()
                        .map(|arm| {
                            Some(HirSwitchStmtArm {
                                condition: match &arm.condition {
                                    Some(condition) => Some(self.lower_expr_with_params(
                                        condition,
                                        param_exprs,
                                        param_types,
                                    )?),
                                    None => None,
                                },
                                body: self.lower_switch_stmt_arm_body_with_params(
                                    &arm.result,
                                    param_exprs,
                                    param_types,
                                )?,
                            })
                        })
                        .collect::<Option<_>>()?,
                },
                _ => HirStmtKind::Expr(self.lower_expr_with_params(
                    expr,
                    param_exprs,
                    param_types,
                )?),
            },
            StmtKind::If {
                condition,
                then_branch,
                else_branch,
            } => HirStmtKind::If {
                condition: self.lower_expr_with_params(condition, param_exprs, param_types)?,
                then_branch: then_branch
                    .iter()
                    .map(|statement| {
                        self.lower_stmt_with_params(statement, param_exprs, param_types)
                    })
                    .collect::<Option<_>>()?,
                else_branch: else_branch
                    .iter()
                    .map(|statement| {
                        self.lower_stmt_with_params(statement, param_exprs, param_types)
                    })
                    .collect::<Option<_>>()?,
            },
            StmtKind::For {
                counter,
                from,
                to,
                step,
                body,
            } => HirStmtKind::For {
                counter: self.lower_decl_symbol(counter, statement.span)?.id,
                from: self.lower_expr_with_params(from, param_exprs, param_types)?,
                to: self.lower_expr_with_params(to, param_exprs, param_types)?,
                step: match step {
                    Some(step) => {
                        Some(self.lower_expr_with_params(step, param_exprs, param_types)?)
                    }
                    None => None,
                },
                body: body
                    .iter()
                    .map(|statement| {
                        self.lower_stmt_with_params(statement, param_exprs, param_types)
                    })
                    .collect::<Option<_>>()?,
            },
            StmtKind::ForIn {
                index,
                value,
                iterable,
                body,
            } => {
                let value_symbol = self.lower_decl_symbol(value, statement.span)?;
                if let Some(type_name) =
                    self.user_type_array_name_of_expr_with_params(iterable, param_exprs)
                {
                    self.mark_symbol_id_user_type(value_symbol.id, type_name);
                }
                HirStmtKind::ForIn {
                    index: match index {
                        Some(index) => Some(self.lower_decl_symbol(index, statement.span)?.id),
                        None => None,
                    },
                    value: value_symbol.id,
                    iterable: self.lower_expr_with_params(iterable, param_exprs, param_types)?,
                    body: body
                        .iter()
                        .map(|statement| {
                            self.lower_stmt_with_params(statement, param_exprs, param_types)
                        })
                        .collect::<Option<_>>()?,
                }
            }
            StmtKind::While { condition, body } => HirStmtKind::While {
                condition: self.lower_expr_with_params(condition, param_exprs, param_types)?,
                body: body
                    .iter()
                    .map(|statement| {
                        self.lower_stmt_with_params(statement, param_exprs, param_types)
                    })
                    .collect::<Option<_>>()?,
            },
            StmtKind::Break => HirStmtKind::Break,
            StmtKind::Continue => HirStmtKind::Continue,
            StmtKind::Decl { name, value, .. } => {
                let symbol = self.lower_decl_symbol(name, statement.span)?;
                if symbol.pine_type.kind == ValueKind::Tuple {
                    if let Some(results) =
                        self.tuple_user_type_array_results_with_params(value, param_exprs)
                    {
                        self.symbol_tuple_user_type_arrays
                            .insert(symbol.id, results);
                    } else {
                        self.symbol_tuple_user_type_arrays.remove(&symbol.id);
                    }
                } else {
                    self.symbol_tuple_user_type_arrays.remove(&symbol.id);
                }
                if let Some(type_name) = self.user_type_name_of_expr_with_params(value, param_exprs)
                {
                    self.mark_symbol_id_user_type(symbol.id, type_name);
                }
                if let Some(type_name) =
                    self.user_type_array_name_of_expr_with_params(value, param_exprs)
                {
                    self.mark_symbol_user_type_array(symbol, type_name);
                }
                let lowered_value = self.lower_expr_with_params(value, param_exprs, param_types)?;
                let symbol =
                    self.lower_alias_decl_symbol_series_id(name, symbol, value, &lowered_value);
                HirStmtKind::Decl {
                    symbol: symbol.id,
                    value: lowered_value,
                }
            }
            StmtKind::Reassign { name, value } => HirStmtKind::Reassign {
                symbol: self.bound_symbol(name, statement.span)?.id,
                value: self.lower_expr_with_params(value, param_exprs, param_types)?,
            },
            StmtKind::FieldReassign {
                receiver,
                field,
                value,
            } => {
                let parts = vec![receiver.clone(), field.clone()];
                let access = self
                    .chart_point_field_access_for_lowering(&parts, statement.span)
                    .map(|access| (access.receiver, access.index))
                    .or_else(|| {
                        self.user_type_field_access_for_lowering(&parts, statement.span)
                            .and_then(|access| {
                                access
                                    .fields
                                    .first()
                                    .map(|field| (access.receiver, field.index))
                            })
                    })?;
                HirStmtKind::FieldReassign {
                    symbol: self.bound_symbol(&access.0, statement.span)?.id,
                    field_index: access.1,
                    value: self.lower_expr_with_params(value, param_exprs, param_types)?,
                }
            }
            StmtKind::ArrayFieldReassign {
                array,
                index,
                field,
                value,
            } => {
                let type_name = self.user_type_array_name_of_expr(array)?;
                let field_index = self
                    .user_types
                    .get(&type_name)?
                    .fields
                    .iter()
                    .position(|candidate| candidate.name == *field)?;
                HirStmtKind::ArrayFieldReassign {
                    array: self.lower_expr_with_params(array, param_exprs, param_types)?,
                    index: self.lower_expr_with_params(index, param_exprs, param_types)?,
                    field_index,
                    value: self.lower_expr_with_params(value, param_exprs, param_types)?,
                }
            }
            StmtKind::TupleDecl { names, value } => {
                let user_type_array_results =
                    self.tuple_user_type_array_results_with_params(value, param_exprs);
                let symbols = names
                    .iter()
                    .map(|name| self.lower_decl_symbol(name, statement.span))
                    .collect::<Option<Vec<_>>>()?;
                for (index, symbol) in symbols.iter().copied().enumerate() {
                    self.symbol_tuple_user_type_arrays.remove(&symbol.id);
                    if symbol.pine_type.kind != ValueKind::UserTypeArray {
                        continue;
                    }
                    let Some(UserTypeArrayIdentityResult::Known(type_name)) =
                        user_type_array_results
                            .as_ref()
                            .and_then(|results| results.get(index))
                    else {
                        return None;
                    };
                    self.mark_symbol_user_type_array(symbol, type_name.clone());
                }
                HirStmtKind::TupleDecl {
                    symbols: symbols.into_iter().map(|symbol| symbol.id).collect(),
                    value: self.lower_expr_with_params(value, param_exprs, param_types)?,
                }
            }
            StmtKind::Function { .. }
            | StmtKind::Import(_)
            | StmtKind::Library(_)
            | StmtKind::Export(_)
            | StmtKind::UserType(_)
            | StmtKind::Method(_) => return None,
            StmtKind::Unsupported { .. } => return None,
        };

        Some(HirStmt { kind })
    }

    pub(crate) fn lower_expr_with_params(
        &mut self,
        expr: &Expr,
        param_exprs: &HashMap<String, HirExpr>,
        param_types: &HashMap<String, PineType>,
    ) -> Option<HirExpr> {
        if !self.record_lowering_node(expr.span) {
            return None;
        }

        if let ExprKind::Identifier(name) = &expr.kind
            && let Some(param_expr) = param_exprs.get(name)
            && self
                .bindings
                .get(&self.binding_key(name, expr.span))
                .is_none_or(|symbol| !self.has_lower_symbol_override(symbol.id))
        {
            return Some(param_expr.clone());
        }

        let pine_type = self.type_of_expr_with_params(expr, param_types)?;
        let series_id = self.lower_expr_series_id(expr, pine_type);

        let kind = match &expr.kind {
            ExprKind::Literal(literal) => HirExprKind::Literal(lower_literal(literal)),
            ExprKind::Identifier(name) => {
                HirExprKind::Symbol(self.bound_symbol(name, expr.span)?.id)
            }
            ExprKind::QualifiedName(parts) => {
                if let Some(field) = self
                    .type_of_bound_chart_point_field_access(parts, expr.span)
                    .or_else(|| self.type_of_chart_point_field_access(parts))
                {
                    let access = self.chart_point_field_access_for_lowering(parts, expr.span)?;
                    let receiver_symbol = self
                        .bound_symbol(&access.receiver, expr.span)
                        .or_else(|| self.scope.resolve(&access.receiver))?;
                    return Some(HirExpr {
                        pine_type: field,
                        series_id,
                        kind: HirExprKind::FieldAccess {
                            value: Box::new(param_exprs.get(&access.receiver).cloned().unwrap_or(
                                HirExpr {
                                    kind: HirExprKind::Symbol(receiver_symbol.id),
                                    pine_type: receiver_symbol.pine_type,
                                    series_id: receiver_symbol.series_id,
                                },
                            )),
                            index: access.index,
                        },
                    });
                }
                if let Some(field) = self
                    .type_of_bound_user_type_field_access(parts, expr.span)
                    .or_else(|| self.type_of_user_type_field_access(parts))
                {
                    let access = self.user_type_field_access_for_lowering(parts, expr.span)?;
                    let receiver_symbol = self
                        .bound_symbol(&access.receiver, expr.span)
                        .or_else(|| self.scope.resolve(&access.receiver))?;
                    let mut value = param_exprs
                        .get(&access.receiver)
                        .cloned()
                        .unwrap_or(HirExpr {
                            kind: HirExprKind::Symbol(receiver_symbol.id),
                            pine_type: receiver_symbol.pine_type,
                            series_id: receiver_symbol.series_id,
                        });
                    let last_index = access.fields.len().saturating_sub(1);
                    for (index, field_access) in access.fields.iter().enumerate() {
                        value = HirExpr {
                            pine_type: field_access.pine_type,
                            series_id: (index == last_index).then_some(series_id).flatten(),
                            kind: HirExprKind::FieldAccess {
                                value: Box::new(value),
                                index: field_access.index,
                            },
                        };
                    }
                    debug_assert_eq!(value.pine_type, field);
                    return Some(value);
                }
                HirExprKind::Builtin(parts.join("."))
            }
            ExprKind::Unary { op, expr } => HirExprKind::Unary {
                op: lower_unary_op(*op),
                expr: Box::new(self.lower_expr_with_params(expr, param_exprs, param_types)?),
            },
            ExprKind::Binary { op, left, right } => HirExprKind::Binary {
                op: lower_binary_op(*op),
                left: Box::new(self.lower_expr_with_params(left, param_exprs, param_types)?),
                right: Box::new(self.lower_expr_with_params(right, param_exprs, param_types)?),
            },
            ExprKind::Ternary {
                condition,
                then_expr,
                else_expr,
            } => HirExprKind::Ternary {
                condition: Box::new(self.lower_expr_with_params(
                    condition,
                    param_exprs,
                    param_types,
                )?),
                then_expr: Box::new(self.lower_expr_with_params(
                    then_expr,
                    param_exprs,
                    param_types,
                )?),
                else_expr: Box::new(self.lower_expr_with_params(
                    else_expr,
                    param_exprs,
                    param_types,
                )?),
            },
            ExprKind::If {
                condition,
                then_branch,
                else_branch,
            } => HirExprKind::Ternary {
                condition: Box::new(self.lower_expr_with_params(
                    condition,
                    param_exprs,
                    param_types,
                )?),
                then_expr: Box::new(self.lower_expr_branch_return(
                    then_branch,
                    param_exprs,
                    param_types,
                )?),
                else_expr: Box::new(self.lower_expr_branch_return(
                    else_branch,
                    param_exprs,
                    param_types,
                )?),
            },
            ExprKind::Switch { selector, arms } => HirExprKind::Switch {
                selector: match selector {
                    Some(selector) => Some(Box::new(self.lower_expr_with_params(
                        selector,
                        param_exprs,
                        param_types,
                    )?)),
                    None => None,
                },
                arms: arms
                    .iter()
                    .map(|arm| {
                        Some(HirSwitchArm {
                            condition: match &arm.condition {
                                Some(condition) => Some(self.lower_expr_with_params(
                                    condition,
                                    param_exprs,
                                    param_types,
                                )?),
                                None => None,
                            },
                            result: self.lower_switch_arm_result_with_params(
                                &arm.result,
                                param_exprs,
                                param_types,
                            )?,
                        })
                    })
                    .collect::<Option<_>>()?,
            },
            ExprKind::For {
                counter,
                from,
                to,
                step,
                body,
            } => {
                let (last, prefix) = body.split_last()?;
                let final_expr;
                let result = match &last.kind {
                    StmtKind::Expr(result) => result,
                    StmtKind::For { .. } | StmtKind::ForIn { .. } | StmtKind::While { .. } => {
                        final_expr = final_loop_statement_expr(last)?;
                        &final_expr
                    }
                    _ => return None,
                };
                HirExprKind::For {
                    counter: self.lower_decl_symbol(counter, expr.span)?.id,
                    from: Box::new(self.lower_expr_with_params(from, param_exprs, param_types)?),
                    to: Box::new(self.lower_expr_with_params(to, param_exprs, param_types)?),
                    step: match step {
                        Some(step) => Some(Box::new(self.lower_expr_with_params(
                            step,
                            param_exprs,
                            param_types,
                        )?)),
                        None => None,
                    },
                    statements: prefix
                        .iter()
                        .map(|statement| {
                            self.lower_stmt_with_params(statement, param_exprs, param_types)
                        })
                        .collect::<Option<_>>()?,
                    result: Box::new(self.lower_expr_with_params(
                        result,
                        param_exprs,
                        param_types,
                    )?),
                }
            }
            ExprKind::ForIn {
                index,
                value,
                iterable,
                body,
            } => {
                let (last, prefix) = body.split_last()?;
                let final_expr;
                let result = match &last.kind {
                    StmtKind::Expr(result) => result,
                    StmtKind::For { .. } | StmtKind::ForIn { .. } | StmtKind::While { .. } => {
                        final_expr = final_loop_statement_expr(last)?;
                        &final_expr
                    }
                    _ => return None,
                };
                let value_symbol = self.lower_decl_symbol(value, expr.span)?;
                if let Some(type_name) =
                    self.user_type_array_name_of_expr_with_params(iterable, param_exprs)
                {
                    self.mark_symbol_id_user_type(value_symbol.id, type_name);
                }
                HirExprKind::ForIn {
                    index: match index {
                        Some(index) => Some(self.lower_decl_symbol(index, expr.span)?.id),
                        None => None,
                    },
                    value: value_symbol.id,
                    iterable: Box::new(self.lower_expr_with_params(
                        iterable,
                        param_exprs,
                        param_types,
                    )?),
                    statements: prefix
                        .iter()
                        .map(|statement| {
                            self.lower_stmt_with_params(statement, param_exprs, param_types)
                        })
                        .collect::<Option<_>>()?,
                    result: Box::new(self.lower_expr_with_params(
                        result,
                        param_exprs,
                        param_types,
                    )?),
                }
            }
            ExprKind::While { condition, body } => {
                let (last, prefix) = body.split_last()?;
                let final_expr;
                let result = match &last.kind {
                    StmtKind::Expr(result) => result,
                    StmtKind::For { .. } | StmtKind::ForIn { .. } | StmtKind::While { .. } => {
                        final_expr = final_loop_statement_expr(last)?;
                        &final_expr
                    }
                    _ => return None,
                };
                HirExprKind::While {
                    condition: Box::new(self.lower_expr_with_params(
                        condition,
                        param_exprs,
                        param_types,
                    )?),
                    statements: prefix
                        .iter()
                        .map(|statement| {
                            self.lower_stmt_with_params(statement, param_exprs, param_types)
                        })
                        .collect::<Option<_>>()?,
                    result: Box::new(self.lower_expr_with_params(
                        result,
                        param_exprs,
                        param_types,
                    )?),
                }
            }
            ExprKind::Tuple(items) => HirExprKind::Tuple(
                items
                    .iter()
                    .map(|item| self.lower_expr_with_params(item, param_exprs, param_types))
                    .collect::<Option<_>>()?,
            ),
            ExprKind::Call { callee, args } => {
                let name = expr_name(callee)?;
                if let Some(constructor) = self
                    .user_type_constructor_for_lowering(&name, args, param_types)
                    .or_else(|| {
                        self.imported_user_type_constructor_for_lowering(&name, args, param_types)
                    })
                {
                    return Some(HirExpr {
                        pine_type,
                        series_id,
                        kind: HirExprKind::UserTypeConstruct {
                            identity: HirUserTypeIdentity {
                                source_id: constructor.identity.source_id.get(),
                                type_name: constructor.identity.name,
                            },
                            fields: constructor
                                .field_args
                                .iter()
                                .map(|arg| {
                                    self.lower_expr_with_params(arg, param_exprs, param_types)
                                })
                                .collect::<Option<_>>()?,
                        },
                    });
                }
                if name == "array.from"
                    && pine_type.kind == ValueKind::UserTypeArray
                    && let Some(type_name) =
                        self.user_type_array_name_of_expr_with_params(expr, param_exprs)
                {
                    return Some(HirExpr {
                        pine_type,
                        series_id,
                        kind: HirExprKind::UserTypeArrayConstruct {
                            type_name,
                            elements: args
                                .iter()
                                .map(|arg| {
                                    self.lower_expr_with_params(
                                        &arg.value,
                                        param_exprs,
                                        param_types,
                                    )
                                })
                                .collect::<Option<_>>()?,
                        },
                    });
                }
                if let Some(result) = self.lower_postfix_call_result_method(
                    callee,
                    args,
                    pine_type,
                    series_id,
                    param_exprs,
                    param_types,
                ) {
                    return result;
                }
                if matches!(callee.kind, ExprKind::QualifiedName(_))
                    && let Some(method_call) = self.lower_alias_qualified_user_method_call(
                        &name,
                        callee.span,
                        args,
                        param_exprs,
                        param_types,
                    )
                {
                    let pure_call_series_id =
                        pure_series::pure_alias_qualified_user_method_call_series_key(
                            self, &name, args,
                        )
                        .and(series_id);
                    let mut method_call = method_call;
                    if let Some(series_id) = pure_call_series_id {
                        method_call.series_id = Some(series_id);
                    }
                    return Some(method_call);
                }
                if let Some(method_call) = self.lower_local_qualified_user_method_call(
                    &name,
                    callee.span,
                    args,
                    param_exprs,
                    param_types,
                ) {
                    let pure_call_series_id =
                        pure_series::pure_local_qualified_user_method_call_series_key(
                            self, &name, args,
                        )
                        .and(series_id);
                    let mut method_call = method_call;
                    if let Some(series_id) = pure_call_series_id {
                        method_call.series_id = Some(series_id);
                    }
                    return Some(method_call);
                }
                if let Some((receiver_name, method_name)) = method_call_parts(callee)
                    && self
                        .bound_symbol(receiver_name, callee.span)
                        .or_else(|| self.scope.resolve(receiver_name))
                        .and_then(|symbol| self.symbol_user_types.get(&symbol.id))
                        .is_some()
                {
                    let pure_call_series_id = pure_series::pure_user_method_call_series_key(
                        self,
                        receiver_name,
                        method_name,
                        callee.span,
                        args,
                    )
                    .and(series_id);
                    let mut call = self.lower_user_method_call(
                        receiver_name,
                        method_name,
                        callee.span,
                        args,
                        param_exprs,
                        param_types,
                    )?;
                    if let Some(series_id) = pure_call_series_id {
                        call.series_id = Some(series_id);
                    }
                    return Some(call);
                }
                if self.functions.contains_key(&name) {
                    let pure_call_series_id =
                        pure_series::pure_udf_call_series_key(self, &name, args).and(series_id);
                    let mut call =
                        self.lower_udf_call(&name, expr.span, args, param_exprs, param_types)?;
                    if let Some(series_id) = pure_call_series_id {
                        call.series_id = Some(series_id);
                    }
                    return Some(call);
                }
                if pine_builtins::get_phase_1_builtin(&name).is_none()
                    && !name.starts_with("map.")
                    && let Some((receiver_name, method_name)) = method_call_parts(callee)
                    && let Some(builtin_name) = param_types
                        .get(receiver_name)
                        .map(|pine_type| pine_type.kind)
                        .or_else(|| {
                            self.bound_symbol(receiver_name, callee.span)
                                .map(|symbol| symbol.pine_type.kind)
                        })
                        .and_then(|receiver_kind| {
                            drawing_method_builtin_name(receiver_kind, method_name)
                                .or_else(|| {
                                    matrix_method_builtin_name(receiver_kind, method_name)
                                        .map(ToOwned::to_owned)
                                })
                                .or_else(|| {
                                    (receiver_kind == ValueKind::Map)
                                        .then(|| map_method_builtin_name(method_name))
                                        .flatten()
                                        .map(ToOwned::to_owned)
                                })
                        })
                        .or_else(|| array_method_builtin_name(method_name).map(ToOwned::to_owned))
                {
                    let receiver_arg = receiver_call_arg(receiver_name, callee.span);
                    let mut method_args = Vec::with_capacity(args.len() + 1);
                    method_args.push(receiver_arg);
                    method_args.extend(args.iter().cloned());
                    let lowered_args = self.lower_builtin_call_args(
                        &builtin_name,
                        &method_args,
                        param_exprs,
                        param_types,
                    )?;
                    return Some(HirExpr {
                        pine_type,
                        series_id,
                        kind: HirExprKind::Call {
                            callee: builtin_name,
                            call_site_id: self.alloc_call_site(),
                            args: lowered_args,
                        },
                    });
                }
                let call_site_id = self.alloc_call_site();
                let lowered_args =
                    self.lower_builtin_call_args(&name, args, param_exprs, param_types)?;
                HirExprKind::Call {
                    callee: name,
                    call_site_id,
                    args: lowered_args,
                }
            }
            ExprKind::History { expr, offset } => {
                let offset = match self
                    .known_history_offset_int_value(offset)
                    .and_then(|value| u32::try_from(value).ok())
                {
                    Some(offset) => HirHistoryOffset::Constant(offset),
                    None => HirHistoryOffset::Dynamic(Box::new(self.lower_expr_with_params(
                        offset,
                        param_exprs,
                        param_types,
                    )?)),
                };
                let mut lowered_expr =
                    self.lower_expr_with_params(expr, param_exprs, param_types)?;
                if lowered_expr.series_id.is_none() {
                    lowered_expr.series_id = self.lower_expr_series_id(
                        expr,
                        PineType::new(Qualifier::Series, lowered_expr.pine_type.kind),
                    );
                }
                HirExprKind::History {
                    expr: Box::new(lowered_expr),
                    offset,
                }
            }
        };

        Some(HirExpr {
            kind,
            pine_type,
            series_id,
        })
    }

    fn lower_expr_series_id(
        &mut self,
        expr: &Expr,
        pine_type: PineType,
    ) -> Option<pine_ir::SeriesId> {
        if (pine_type.qualifier != Qualifier::Series && !is_collection_kind(pine_type.kind))
            || pine_type.kind == ValueKind::Tuple
        {
            return None;
        }

        if let ExprKind::Identifier(name) = &expr.kind {
            return self
                .bound_symbol(name, expr.span)
                .and_then(|symbol| symbol.series_id);
        }

        if pine_type.qualifier == Qualifier::Series
            && !is_collection_kind(pine_type.kind)
            && let Some(key) = self.pure_expr_series_key(expr)
        {
            if let Some(series_id) = self.pure_expr_series_ids.get(&key).copied() {
                return Some(series_id);
            }
            let series_id = self.alloc_series();
            self.pure_expr_series_ids.insert(key, series_id);
            return Some(series_id);
        }

        Some(self.alloc_series())
    }

    fn pure_expr_series_key(&self, expr: &Expr) -> Option<String> {
        pure_series::pure_expr_series_key(self, expr)
    }
}
