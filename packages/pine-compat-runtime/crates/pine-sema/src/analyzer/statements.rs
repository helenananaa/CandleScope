use crate::prelude::*;
use crate::resolver::ScopeResolver;

mod declarations;
mod for_in;

#[derive(Clone)]
pub(crate) struct SymbolState {
    scope: ScopeResolver,
    symbol_user_types: HashMap<SymbolId, String>,
    symbol_user_type_identities: HashMap<SymbolId, UserTypeIdentity>,
    symbol_init_exprs: HashMap<SymbolId, SourcedExpr>,
    typed_na_scalar_symbols: std::collections::HashSet<SymbolId>,
    non_scalar_udt_varip_symbols: std::collections::HashSet<SymbolId>,
    symbol_user_type_arrays: HashMap<SymbolId, String>,
    symbol_tuple_element_types: HashMap<SymbolId, Vec<PineType>>,
    symbol_tuple_user_type_arrays: HashMap<SymbolId, Vec<UserTypeArrayIdentityResult>>,
    symbol_maps: HashMap<SymbolId, MapTypeInfo>,
    const_int_symbols: HashMap<SymbolId, i64>,
    const_numeric_symbols: HashMap<SymbolId, f64>,
    const_string_symbols: HashMap<SymbolId, String>,
    const_bool_symbols: HashMap<SymbolId, bool>,
    const_color_symbols: HashMap<SymbolId, u32>,
}

impl Analyzer {
    pub(crate) fn analyze_program(&mut self, program: &Program) {
        self.register_user_types(program);
        self.register_methods(program);
        self.register_functions(program);
        for statement in &program.statements {
            self.analyze_stmt(statement);
        }
    }

    pub(crate) fn analyze_stmt(&mut self, statement: &Stmt) {
        match &statement.kind {
            StmtKind::Expr(expr) => {
                if let ExprKind::Switch { selector, arms } = &expr.kind {
                    self.analyze_switch_stmt(selector.as_deref(), arms, expr.span);
                } else {
                    self.analyze_expr(expr);
                }
            }
            StmtKind::Import(_) => {
                self.compatibility.supported.push(FeatureUse {
                    feature: "import".to_owned(),
                    span: statement.span,
                });
            }
            StmtKind::Library(_) => {
                self.unsupported(
                    "library",
                    unsupported_syntax_reason("library"),
                    statement.span,
                );
            }
            StmtKind::Export(_) => {
                self.unsupported(
                    "export",
                    unsupported_syntax_reason("export"),
                    statement.span,
                );
            }
            StmtKind::UserType(_) => {
                if self.block_depth > 0 || self.function_depth > 0 {
                    self.diagnostics.push(Diagnostic::error(
                        "E_UDT_DECL_LOCATION",
                        "user-defined type declarations must be top-level",
                        statement.span,
                    ));
                }
                self.compatibility.supported.push(FeatureUse {
                    feature: "user-defined types".to_owned(),
                    span: statement.span,
                });
            }
            StmtKind::Method(_) => {
                if self.block_depth > 0 || self.function_depth > 0 {
                    self.diagnostics.push(Diagnostic::error(
                        "E_METHOD_DECL_LOCATION",
                        "user-defined method declarations must be top-level",
                        statement.span,
                    ));
                }
                self.compatibility.supported.push(FeatureUse {
                    feature: "user-defined methods".to_owned(),
                    span: statement.span,
                });
            }
            StmtKind::If {
                condition,
                then_branch,
                else_branch,
            } => {
                let condition_type = self.analyze_expr(condition);
                if let Some(condition_type) = condition_type {
                    self.expect_bool(condition_type, condition.span);
                }
                let condition_qualifier =
                    condition_type.map_or(Qualifier::Const, |pine_type| pine_type.qualifier);
                let condition_value = self.known_const_bool_value(condition);
                self.compatibility.supported.push(FeatureUse {
                    feature: "if".to_owned(),
                    span: statement.span,
                });

                self.block_depth += 1;
                self.assignment_qualifier_context.push(condition_qualifier);
                match condition_value {
                    Some(true) => {
                        self.analyze_statement_branch(then_branch);
                        self.analyze_statement_branch_without_symbol_effects(else_branch);
                    }
                    Some(false) => {
                        self.analyze_statement_branch_without_symbol_effects(then_branch);
                        self.analyze_statement_branch(else_branch);
                    }
                    None => {
                        self.analyze_statement_branch(then_branch);
                        self.analyze_statement_branch(else_branch);
                    }
                }
                self.assignment_qualifier_context.pop();
                self.block_depth -= 1;
            }
            StmtKind::For {
                counter,
                from,
                to,
                step,
                body,
            } => {
                let from_type = self.analyze_expr(from);
                let to_type = self.analyze_expr(to);
                let step_type = step.as_ref().and_then(|step| self.analyze_expr(step));
                if let Some(from_type) = from_type {
                    self.expect_int(from_type, from.span);
                }
                if let Some(to_type) = to_type {
                    self.expect_int(to_type, to.span);
                }
                if let Some((step, step_type)) = step.as_ref().zip(step_type) {
                    self.expect_int(step_type, step.span);
                    self.expect_non_zero_loop_step(step);
                }
                self.compatibility.supported.push(FeatureUse {
                    feature: "for".to_owned(),
                    span: statement.span,
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
                self.bind_symbol(counter, statement.span, counter_symbol);
                self.symbol_tuple_element_types.remove(&counter_symbol.id);
                self.symbol_tuple_user_type_arrays
                    .remove(&counter_symbol.id);
                for body_statement in body {
                    self.analyze_stmt(body_statement);
                }
                self.scope.pop_scope();
                self.assignment_qualifier_context.pop();
                self.loop_depth -= 1;
                self.block_depth -= 1;
            }
            StmtKind::ForIn {
                index,
                value,
                iterable,
                body,
            } => {
                self.analyze_for_in_stmt(index.as_deref(), value, iterable, body, statement.span);
            }
            StmtKind::While { condition, body } => {
                let condition_type = self.analyze_expr(condition);
                if let Some(condition_type) = condition_type {
                    self.expect_bool(condition_type, condition.span);
                }
                let condition_qualifier =
                    condition_type.map_or(Qualifier::Const, |pine_type| pine_type.qualifier);
                self.compatibility.supported.push(FeatureUse {
                    feature: "while".to_owned(),
                    span: statement.span,
                });

                self.block_depth += 1;
                self.loop_depth += 1;
                self.assignment_qualifier_context.push(condition_qualifier);
                self.scope.push_scope();
                for body_statement in body {
                    self.analyze_stmt(body_statement);
                }
                self.scope.pop_scope();
                self.assignment_qualifier_context.pop();
                self.loop_depth -= 1;
                self.block_depth -= 1;
            }
            StmtKind::Break => {
                if self.loop_depth == 0 {
                    self.diagnostics.push(Diagnostic::error(
                        "E_LOOP_CONTROL",
                        "`break` can only be used inside a loop",
                        statement.span,
                    ));
                }
            }
            StmtKind::Continue => {
                if self.loop_depth == 0 {
                    self.diagnostics.push(Diagnostic::error(
                        "E_LOOP_CONTROL",
                        "`continue` can only be used inside a loop",
                        statement.span,
                    ));
                }
            }
            StmtKind::Function { .. } => {
                if self.block_depth > 0 || self.function_depth > 0 {
                    self.unsupported(
                        "block_local_function",
                        "nested function declarations are not supported",
                        statement.span,
                    );
                }
            }
            StmtKind::Decl {
                mode,
                declared_type,
                name,
                value,
            } => {
                let diagnostic_start = self.diagnostics.len();
                let value_type = self.analyze_expr(value).unwrap_or(UNKNOWN);
                let value_has_errors = self.diagnostics[diagnostic_start..]
                    .iter()
                    .any(|diagnostic| diagnostic.severity == Severity::Error);
                if value_type.kind == ValueKind::Void {
                    self.diagnostics.push(Diagnostic::error(
                        "E_DECL_VALUE",
                        "declarations must be initialized with a value-producing expression",
                        value.span,
                    ));
                }
                let declared_pine_type =
                    self.declared_pine_type(declared_type.as_ref(), statement.span);
                let declared_user_type_name = declared_type
                    .as_ref()
                    .and_then(DeclaredType::named_type)
                    .filter(|type_name| self.is_known_user_type_name(type_name))
                    .map(str::to_owned);
                let declared_user_type_array_name = declared_type
                    .as_ref()
                    .and_then(|declared_type| self.declared_user_type_array_name(declared_type));
                let declared_map_info = declared_type
                    .as_ref()
                    .and_then(|declared_type| self.declared_map_type_info(declared_type));
                let is_bare_map_decl = matches!(
                    declared_type,
                    Some(DeclaredType::Named(type_name)) if type_name == "map"
                );
                let inferred_bare_map_info = (is_bare_map_decl
                    && value_type.kind == ValueKind::Map)
                    .then(|| self.map_type_of_expr(value))
                    .flatten();
                let inferred_varip_user_type_name = (matches!(mode, pine_syntax::DeclMode::Varip)
                    && declared_user_type_name.is_none())
                .then(|| {
                    self.direct_user_type_constructor_name(value)
                        .or_else(|| self.direct_user_type_alias_name(value))
                })
                .flatten();
                let inferred_varip_user_type_array_name =
                    (matches!(mode, pine_syntax::DeclMode::Varip)
                        && declared_user_type_array_name.is_none())
                    .then(|| self.user_type_array_name_of_expr(value))
                    .flatten();
                if let Some(target_type) = declared_pine_type {
                    self.validate_typed_declaration(name, target_type, value_type, statement.span);
                    if let Some(target_user_type_name) = declared_user_type_name.as_deref() {
                        self.validate_user_type_value_assignment(
                            name,
                            target_user_type_name,
                            value,
                            value_type,
                            statement.span,
                        );
                    }
                    if let Some(target_type_name) = declared_user_type_array_name.as_deref() {
                        self.validate_user_type_array_value_assignment(
                            name,
                            target_type_name,
                            value,
                            value_type,
                            statement.span,
                        );
                    }
                    if let Some(target_info) = declared_map_info {
                        self.validate_map_value_assignment(
                            name,
                            target_info,
                            value,
                            value_type,
                            statement.span,
                        );
                    }
                    self.compatibility.supported.push(FeatureUse {
                        feature: format!(
                            "{} typed declarations",
                            declared_type
                                .as_ref()
                                .map_or_else(|| "typed".to_owned(), DeclaredType::canonical_name)
                        ),
                        span: statement.span,
                    });
                } else if inferred_bare_map_info.is_some() {
                    self.compatibility.supported.push(FeatureUse {
                        feature: "map typed declarations".to_owned(),
                        span: statement.span,
                    });
                } else if is_bare_map_decl {
                    self.diagnostics.push(Diagnostic::error(
                        "E_DECL_TYPE",
                        "typed declaration `map` is not supported",
                        statement.span,
                    ));
                }
                let symbol_type = declared_pine_type
                    .map(|target_type| declared_symbol_type(target_type, value_type))
                    .unwrap_or(value_type);
                let tuple_element_types = (symbol_type.kind == ValueKind::Tuple)
                    .then(|| self.tuple_element_types(value))
                    .flatten();
                let tuple_user_type_arrays = (symbol_type.kind == ValueKind::Tuple)
                    .then(|| self.tuple_user_type_array_results(value))
                    .flatten();
                let existing_tuple_user_type_arrays = (self.block_depth == 0
                    && self.function_depth == 0)
                    .then(|| {
                        self.scope.resolve(name).and_then(|symbol| {
                            self.symbol_tuple_user_type_arrays.get(&symbol.id).cloned()
                        })
                    })
                    .flatten();
                let tuple_identity_is_valid = symbol_type.kind != ValueKind::Tuple
                    || value_has_errors
                    || tuple_element_types.as_ref().is_some_and(|element_types| {
                        self.validate_tuple_user_type_array_identity_results(
                            element_types,
                            tuple_user_type_arrays.as_deref(),
                            existing_tuple_user_type_arrays.as_deref(),
                            value.span,
                        )
                    });
                let is_typed_na_scalar_decl = declared_pine_type.is_some()
                    && value_type.kind == ValueKind::Na
                    && is_scalar_assignment_kind(symbol_type.kind)
                    && symbol_type.kind != ValueKind::Na;
                let is_non_scalar_typed_na_udt_varip_decl =
                    matches!(mode, pine_syntax::DeclMode::Varip)
                        && declared_pine_type.is_some()
                        && value_type.kind == ValueKind::Na
                        && symbol_type.kind == ValueKind::UserType
                        && declared_user_type_name
                            .as_deref()
                            .is_some_and(|type_name| !self.is_scalar_tree_user_type(type_name));
                let const_int_value =
                    const_int_symbol_value(symbol_type, self.known_const_int_value(value));
                let const_numeric_value =
                    const_numeric_symbol_value(symbol_type, self.known_const_numeric_value(value));
                let const_string_value =
                    const_string_symbol_value(symbol_type, self.known_const_string_value(value));
                let const_bool_value =
                    const_bool_symbol_value(symbol_type, self.known_const_bool_value(value));
                let const_color_value =
                    const_color_symbol_value(symbol_type, self.known_const_color_value(value));
                let (persistence, var_slot_id) = self.declaration_persistence(
                    *mode,
                    symbol_type,
                    declared_user_type_name
                        .as_deref()
                        .or(inferred_varip_user_type_name.as_deref()),
                    declared_user_type_array_name
                        .as_deref()
                        .or(inferred_varip_user_type_array_name.as_deref()),
                    is_non_scalar_typed_na_udt_varip_decl,
                    statement.span,
                );
                let symbol = if self.block_depth > 0 || self.function_depth > 0 {
                    self.define_local_symbol_with_persistence(
                        name,
                        symbol_type,
                        persistence,
                        var_slot_id,
                        self.function_depth == 0,
                    )
                } else {
                    self.define_symbol_with_persistence(name, symbol_type, persistence, var_slot_id)
                };
                if symbol_type.kind != ValueKind::Tuple {
                    self.symbol_tuple_element_types.remove(&symbol.id);
                    self.symbol_tuple_user_type_arrays.remove(&symbol.id);
                } else if tuple_identity_is_valid {
                    if let Some(element_types) = tuple_element_types {
                        self.symbol_tuple_element_types
                            .insert(symbol.id, element_types);
                    }
                    if let Some(results) = tuple_user_type_arrays {
                        self.symbol_tuple_user_type_arrays
                            .insert(symbol.id, results);
                    }
                }
                if let Some(type_name) = declared_user_type_name {
                    self.mark_symbol_user_type(symbol, type_name);
                } else if let Some(type_name) = declared_user_type_array_name {
                    self.mark_symbol_user_type_array(symbol, type_name);
                } else if let Some(type_name) = self.user_type_name_of_expr(value) {
                    self.mark_symbol_user_type(symbol, type_name);
                }
                if is_typed_na_scalar_decl {
                    self.typed_na_scalar_symbols.insert(symbol.id);
                }
                if is_non_scalar_typed_na_udt_varip_decl {
                    self.non_scalar_udt_varip_symbols.insert(symbol.id);
                }
                if symbol_type.kind == ValueKind::UserTypeArray
                    && let Some(type_name) = self.user_type_array_name_of_expr(value)
                {
                    self.mark_symbol_user_type_array(symbol, type_name);
                }
                if symbol_type.kind == ValueKind::Map
                    && let Some(info) = declared_map_info
                        .or(inferred_bare_map_info)
                        .or_else(|| self.map_type_of_expr(value))
                {
                    self.mark_symbol_map(symbol, info);
                }
                if let Some(value) = const_int_value {
                    self.const_int_symbols.insert(symbol.id, value);
                } else {
                    self.const_int_symbols.remove(&symbol.id);
                }
                if let Some(value) = const_numeric_value {
                    self.const_numeric_symbols.insert(symbol.id, value);
                } else {
                    self.const_numeric_symbols.remove(&symbol.id);
                }
                if let Some(value) = const_string_value {
                    self.const_string_symbols.insert(symbol.id, value);
                } else {
                    self.const_string_symbols.remove(&symbol.id);
                }
                if let Some(value) = const_bool_value {
                    self.const_bool_symbols.insert(symbol.id, value);
                } else {
                    self.const_bool_symbols.remove(&symbol.id);
                }
                if let Some(value) = const_color_value {
                    self.const_color_symbols.insert(symbol.id, value);
                } else {
                    self.const_color_symbols.remove(&symbol.id);
                }
                self.symbol_init_exprs.insert(
                    symbol.id,
                    SourcedExpr {
                        source_context_id: self.current_source_context_id(),
                        expr: value.clone(),
                    },
                );
                self.bind_symbol(name, statement.span, symbol);
            }
            StmtKind::Reassign { name, value } => {
                let diagnostic_start = self.diagnostics.len();
                if self.scope.resolve(name).is_none() {
                    self.diagnostics.push(Diagnostic::error(
                        "E_UNKNOWN_SYMBOL",
                        format!("cannot reassign unknown symbol `{name}`"),
                        statement.span,
                    ));
                } else if self.function_depth > 0 && self.scope.resolves_to_global(name) {
                    self.unsupported(
                        "function_side_effect",
                        "reassigning global variables inside user-defined functions is not supported",
                        statement.span,
                    );
                }
                let value_type = self.analyze_expr(value);
                let value_has_errors = self.diagnostics[diagnostic_start..]
                    .iter()
                    .any(|diagnostic| diagnostic.severity == Severity::Error);
                if let (Some(target_type), Some(value_type)) = (
                    self.scope.resolve(name).map(|symbol| symbol.pine_type),
                    value_type,
                ) {
                    let symbol = self.scope.resolve(name);
                    let value_type = self.assignment_contextualized_type(value_type);
                    let invalid_non_scalar_udt_varip_reassign =
                        symbol.as_ref().is_some_and(|symbol| {
                            self.non_scalar_udt_varip_symbols.contains(&symbol.id)
                        }) && value_type.kind != ValueKind::Na;
                    if invalid_non_scalar_udt_varip_reassign {
                        self.unsupported(
                            "varip",
                            VARIP_NON_SCALAR_UDT_ASSIGN_UNSUPPORTED_REASON,
                            statement.span,
                        );
                    }
                    let is_typed_na_scalar_reassignment = symbol
                        .as_ref()
                        .is_some_and(|symbol| self.typed_na_scalar_symbols.contains(&symbol.id))
                        && value_type.kind != ValueKind::Na
                        && is_scalar_assignment_kind(value_type.kind);
                    let reassigned_type = if is_typed_na_scalar_reassignment {
                        typed_na_scalar_reassigned_symbol_type(target_type, value_type)
                    } else {
                        reassigned_symbol_type(target_type, value_type)
                    };
                    let tuple_element_types = (target_type.kind == ValueKind::Tuple
                        && value_type.kind == ValueKind::Tuple)
                        .then(|| self.tuple_element_types(value))
                        .flatten();
                    let tuple_user_type_arrays = (target_type.kind == ValueKind::Tuple
                        && value_type.kind == ValueKind::Tuple)
                        .then(|| self.tuple_user_type_array_results(value))
                        .flatten();
                    let previous_tuple_user_type_arrays = symbol
                        .and_then(|symbol| self.symbol_tuple_user_type_arrays.get(&symbol.id))
                        .cloned();
                    let tuple_identity_is_valid = target_type.kind != ValueKind::Tuple
                        || value_has_errors
                        || tuple_element_types.as_ref().is_some_and(|element_types| {
                            self.validate_tuple_user_type_array_identity_results(
                                element_types,
                                tuple_user_type_arrays.as_deref(),
                                previous_tuple_user_type_arrays.as_deref(),
                                value.span,
                            )
                        });
                    let const_int_value =
                        const_int_symbol_value(reassigned_type, self.known_const_int_value(value));
                    let const_numeric_value = const_numeric_symbol_value(
                        reassigned_type,
                        self.known_const_numeric_value(value),
                    );
                    let const_string_value = const_string_symbol_value(
                        reassigned_type,
                        self.known_const_string_value(value),
                    );
                    let const_bool_value = const_bool_symbol_value(
                        reassigned_type,
                        self.known_const_bool_value(value),
                    );
                    let const_color_value = const_color_symbol_value(
                        reassigned_type,
                        self.known_const_color_value(value),
                    );
                    if !can_reassign(target_type, value_type) {
                        self.validate_assignment(name, target_type, value_type, statement.span);
                    }
                    if target_type.kind == ValueKind::UserType
                        && let Some(symbol) = self.scope.resolve(name)
                        && let Some(target_type_name) = self.symbol_user_types.get(&symbol.id)
                    {
                        let target_type_name = target_type_name.clone();
                        self.validate_user_type_value_assignment(
                            name,
                            &target_type_name,
                            value,
                            value_type,
                            statement.span,
                        );
                    }
                    if target_type.kind == ValueKind::UserTypeArray
                        && let Some(symbol) = self.scope.resolve(name)
                        && let Some(target_type_name) = self.symbol_user_type_arrays.get(&symbol.id)
                    {
                        let target_type_name = target_type_name.clone();
                        self.validate_user_type_array_value_assignment(
                            name,
                            &target_type_name,
                            value,
                            value_type,
                            statement.span,
                        );
                    }
                    if target_type.kind == ValueKind::Map
                        && let Some(symbol) = self.scope.resolve(name)
                    {
                        if let Some(target_info) = self.symbol_maps.get(&symbol.id).copied() {
                            self.validate_map_value_assignment(
                                name,
                                target_info,
                                value,
                                value_type,
                                statement.span,
                            );
                        } else if let Some(value_info) = self.map_type_of_expr(value) {
                            self.mark_symbol_map(symbol, value_info);
                        }
                    }
                    if can_reassign(target_type, value_type)
                        && !invalid_non_scalar_udt_varip_reassign
                    {
                        self.update_symbol_type(name, reassigned_type);
                    }
                    if let Some(symbol) = symbol {
                        if can_reassign(target_type, value_type)
                            && target_type.kind == ValueKind::Tuple
                            && tuple_identity_is_valid
                        {
                            if !self.symbol_tuple_element_types.contains_key(&symbol.id)
                                && let Some(element_types) = tuple_element_types
                            {
                                self.symbol_tuple_element_types
                                    .insert(symbol.id, element_types);
                            }
                            if !self.symbol_tuple_user_type_arrays.contains_key(&symbol.id)
                                && let Some(results) = tuple_user_type_arrays
                            {
                                self.symbol_tuple_user_type_arrays
                                    .insert(symbol.id, results);
                            }
                        }
                        if can_reassign(target_type, value_type)
                            && value_type.kind != ValueKind::Na
                            && !invalid_non_scalar_udt_varip_reassign
                        {
                            self.typed_na_scalar_symbols.remove(&symbol.id);
                        }
                        self.symbol_init_exprs.remove(&symbol.id);
                        if can_reassign(target_type, value_type)
                            && let Some(value) = const_int_value
                        {
                            self.const_int_symbols.insert(symbol.id, value);
                        } else {
                            self.const_int_symbols.remove(&symbol.id);
                        }
                        if can_reassign(target_type, value_type)
                            && let Some(value) = const_numeric_value
                        {
                            self.const_numeric_symbols.insert(symbol.id, value);
                        } else {
                            self.const_numeric_symbols.remove(&symbol.id);
                        }
                        if can_reassign(target_type, value_type)
                            && let Some(value) = const_string_value
                        {
                            self.const_string_symbols.insert(symbol.id, value);
                        } else {
                            self.const_string_symbols.remove(&symbol.id);
                        }
                        if can_reassign(target_type, value_type)
                            && let Some(value) = const_bool_value
                        {
                            self.const_bool_symbols.insert(symbol.id, value);
                        } else {
                            self.const_bool_symbols.remove(&symbol.id);
                        }
                        if can_reassign(target_type, value_type)
                            && let Some(value) = const_color_value
                        {
                            self.const_color_symbols.insert(symbol.id, value);
                        } else {
                            self.const_color_symbols.remove(&symbol.id);
                        }
                    }
                }
                if let Some(symbol) = self.scope.resolve(name) {
                    self.bind_symbol(name, statement.span, symbol);
                }
            }
            StmtKind::FieldReassign {
                receiver,
                field,
                value,
            } => {
                let target = if let Some(target) =
                    self.resolve_chart_point_field_mutation(receiver, field, statement.span)
                {
                    Some((target.pine_type, None, "chart.point field mutation", None))
                } else {
                    self.resolve_user_type_field_mutation(receiver, field, statement.span)
                        .map(|target| {
                            (
                                target.pine_type,
                                target.user_type_name,
                                "user-defined type field mutation",
                                Some(target.receiver_symbol),
                            )
                        })
                };
                let receiver_is_global = self.scope.resolves_to_global(receiver);
                let target_receiver_symbol = target
                    .as_ref()
                    .and_then(|(_, _, _, receiver_symbol)| *receiver_symbol);
                let receiver_is_non_scalar_udt_varip = target_receiver_symbol
                    .as_ref()
                    .is_some_and(|symbol| self.non_scalar_udt_varip_symbols.contains(&symbol.id));
                if receiver_is_non_scalar_udt_varip {
                    self.unsupported(
                        "varip",
                        VARIP_NON_SCALAR_UDT_ASSIGN_UNSUPPORTED_REASON,
                        statement.span,
                    );
                }
                let receiver_is_function_param = target
                    .as_ref()
                    .and_then(|(_, _, _, receiver_symbol)| receiver_symbol.as_ref())
                    .is_some_and(|symbol| {
                        self.function_param_symbols
                            .last()
                            .is_some_and(|params| params.contains(&symbol.id))
                    });
                let is_method_context = self
                    .function_context_is_method
                    .last()
                    .copied()
                    .unwrap_or(false);
                let allowed_function_local_udt_mutation =
                    target
                        .as_ref()
                        .is_some_and(|(_, _, feature, receiver_symbol)| {
                            *feature == "user-defined type field mutation"
                                && receiver_symbol.is_some()
                                && !receiver_is_global
                                && !receiver_is_function_param
                        });
                if self.function_depth > 0 && !allowed_function_local_udt_mutation {
                    let reason = match target.as_ref().map(|(_, _, feature, _)| *feature) {
                        Some("user-defined type field mutation") if is_method_context => {
                            "mutating user-defined type fields inside methods is not supported"
                        }
                        Some("user-defined type field mutation") if receiver_is_function_param => {
                            "mutating user-defined type parameter fields inside user-defined functions is not supported"
                        }
                        Some("user-defined type field mutation") if receiver_is_global => {
                            "mutating fields on global user-defined type values inside user-defined functions is not supported"
                        }
                        Some("user-defined type field mutation") => {
                            "mutating user-defined type fields inside user-defined functions is not supported"
                        }
                        Some("chart.point field mutation") => {
                            "mutating chart.point fields inside user-defined functions or methods is not supported"
                        }
                        _ => {
                            "mutating object fields inside user-defined functions or methods is not supported"
                        }
                    };
                    self.unsupported("function_side_effect", reason, statement.span);
                }
                let value_type = self.analyze_expr(value);
                if let Some(receiver_symbol) = target_receiver_symbol {
                    self.symbol_init_exprs.remove(&receiver_symbol.id);
                }
                if let (Some((target_type, target_user_type, feature, _)), Some(value_type)) =
                    (target, value_type)
                {
                    let name = format!("{receiver}.{field}");
                    if let Some(target_user_type) = target_user_type {
                        self.validate_user_type_field_assignment(
                            &name,
                            &target_user_type,
                            value,
                            value_type,
                            statement.span,
                        );
                    } else {
                        self.validate_assignment(&name, target_type, value_type, statement.span);
                    }
                    self.compatibility.supported.push(FeatureUse {
                        feature: feature.to_owned(),
                        span: statement.span,
                    });
                }
            }
            StmtKind::ArrayFieldReassign {
                array,
                index,
                field,
                value,
            } => {
                if self.function_depth > 0 {
                    self.unsupported(
                        "function_side_effect",
                        "mutating user-defined type array fields inside user-defined functions or methods is not supported",
                        statement.span,
                    );
                }

                let array_type = self.analyze_expr(array);
                let index_type = self.analyze_expr(index);
                let value_type = self.analyze_expr(value);

                if let Some(index_type) = index_type
                    && let Some(diagnostic) = call_arg_accepts_type_expected_diagnostic(
                        "array.get",
                        "index",
                        Accepts::SimpleIntCompatible,
                        index_type,
                        index.span,
                    )
                {
                    self.diagnostics.push(diagnostic);
                }

                let Some(array_type) = array_type else {
                    return;
                };
                if array_type.kind != ValueKind::UserTypeArray {
                    self.diagnostics.push(Diagnostic::error(
                        "E_UDT_FIELD_MUTATION",
                        "chained UDT array field mutation requires a same-local scalar-tree UDT array",
                        statement.span,
                    ));
                    return;
                }
                let Some(type_name) = self.user_type_array_name_of_expr(array) else {
                    self.diagnostics.push(Diagnostic::error(
                        "E_UDT_FIELD_MUTATION",
                        "cannot resolve UDT element identity for chained array field mutation",
                        statement.span,
                    ));
                    return;
                };
                if type_name.contains('.') {
                    self.diagnostics.push(Diagnostic::error(
                        "E_UDT_FIELD_MUTATION",
                        "chained UDT array field mutation supports only same-local scalar-tree UDT arrays; imported UDT array field mutation is not supported",
                        statement.span,
                    ));
                    return;
                }
                let Some(user_type) = self.user_types.get(&type_name) else {
                    self.diagnostics.push(Diagnostic::error(
                        "E_UDT_FIELD_MUTATION",
                        format!("unknown UDT array element `{type_name}`"),
                        statement.span,
                    ));
                    return;
                };
                let Some((field_type, field_user_type_name)) = user_type
                    .fields
                    .iter()
                    .find(|candidate| candidate.name == *field)
                    .map(|field_info| (field_info.pine_type, field_info.user_type_name.clone()))
                else {
                    self.diagnostics.push(Diagnostic::error(
                        "E_UDT_UNKNOWN_FIELD",
                        format!("unknown field `{field}` on `{type_name}`"),
                        statement.span,
                    ));
                    return;
                };
                if let Some(value_type) = value_type {
                    let name = format!("array.get(...).{field}");
                    if let Some(target_user_type) = field_user_type_name {
                        self.validate_user_type_field_assignment(
                            &name,
                            &target_user_type,
                            value,
                            value_type,
                            statement.span,
                        );
                    } else {
                        self.validate_assignment(&name, field_type, value_type, statement.span);
                    }
                    self.compatibility.supported.push(FeatureUse {
                        feature: "user-defined type array field mutation".to_owned(),
                        span: statement.span,
                    });
                }
            }
            StmtKind::TupleDecl { .. } => {
                self.analyze_tuple_decl(statement);
            }
            StmtKind::Unsupported { feature } => {
                self.unsupported(feature, unsupported_syntax_reason(feature), statement.span);
            }
        }
    }

    fn assignment_contextualized_type(&self, value_type: PineType) -> PineType {
        if !is_scalar_assignment_kind(value_type.kind) {
            return value_type;
        }
        let qualifier = self
            .assignment_qualifier_context
            .iter()
            .copied()
            .fold(value_type.qualifier, strongest_qualifier);
        PineType::new(qualifier, value_type.kind)
    }

    fn analyze_statement_branch(&mut self, statements: &[Stmt]) {
        self.scope.push_scope();
        for statement in statements {
            self.analyze_stmt(statement);
        }
        self.scope.pop_scope();
    }

    pub(crate) fn analyze_without_symbol_effects<T>(
        &mut self,
        analyze: impl FnOnce(&mut Self) -> T,
    ) -> T {
        let state = self.symbol_state();
        let result = analyze(self);
        self.restore_symbol_state(state);
        result
    }

    fn analyze_statement_branch_without_symbol_effects(&mut self, statements: &[Stmt]) {
        self.analyze_without_symbol_effects(|analyzer| {
            analyzer.analyze_statement_branch(statements);
        });
    }

    pub(crate) fn symbol_state(&self) -> SymbolState {
        SymbolState {
            scope: self.scope.clone(),
            symbol_user_types: self.symbol_user_types.clone(),
            symbol_user_type_identities: self.symbol_user_type_identities.clone(),
            symbol_init_exprs: self.symbol_init_exprs.clone(),
            typed_na_scalar_symbols: self.typed_na_scalar_symbols.clone(),
            non_scalar_udt_varip_symbols: self.non_scalar_udt_varip_symbols.clone(),
            symbol_user_type_arrays: self.symbol_user_type_arrays.clone(),
            symbol_tuple_element_types: self.symbol_tuple_element_types.clone(),
            symbol_tuple_user_type_arrays: self.symbol_tuple_user_type_arrays.clone(),
            symbol_maps: self.symbol_maps.clone(),
            const_int_symbols: self.const_int_symbols.clone(),
            const_numeric_symbols: self.const_numeric_symbols.clone(),
            const_string_symbols: self.const_string_symbols.clone(),
            const_bool_symbols: self.const_bool_symbols.clone(),
            const_color_symbols: self.const_color_symbols.clone(),
        }
    }

    pub(crate) fn restore_symbol_state(&mut self, state: SymbolState) {
        self.scope = state.scope;
        self.symbol_user_types = state.symbol_user_types;
        self.symbol_user_type_identities = state.symbol_user_type_identities;
        self.symbol_init_exprs = state.symbol_init_exprs;
        self.typed_na_scalar_symbols = state.typed_na_scalar_symbols;
        self.non_scalar_udt_varip_symbols = state.non_scalar_udt_varip_symbols;
        self.symbol_user_type_arrays = state.symbol_user_type_arrays;
        self.symbol_tuple_element_types = state.symbol_tuple_element_types;
        self.symbol_tuple_user_type_arrays = state.symbol_tuple_user_type_arrays;
        self.symbol_maps = state.symbol_maps;
        self.const_int_symbols = state.const_int_symbols;
        self.const_numeric_symbols = state.const_numeric_symbols;
        self.const_string_symbols = state.const_string_symbols;
        self.const_bool_symbols = state.const_bool_symbols;
        self.const_color_symbols = state.const_color_symbols;
    }
}

fn declared_symbol_type(target_type: PineType, value_type: PineType) -> PineType {
    if value_type.kind == ValueKind::Na {
        return target_type;
    }
    PineType::new(value_type.qualifier, target_type.kind)
}

fn const_int_symbol_value(symbol_type: PineType, value: Option<i64>) -> Option<i64> {
    (symbol_type.qualifier == Qualifier::Const && symbol_type.kind == ValueKind::Int)
        .then_some(value)
        .flatten()
}

fn const_numeric_symbol_value(symbol_type: PineType, value: Option<f64>) -> Option<f64> {
    (symbol_type.qualifier == Qualifier::Const
        && matches!(symbol_type.kind, ValueKind::Int | ValueKind::Float))
    .then_some(value)
    .flatten()
}

fn const_string_symbol_value(symbol_type: PineType, value: Option<String>) -> Option<String> {
    (symbol_type.qualifier == Qualifier::Const && symbol_type.kind == ValueKind::String)
        .then_some(value)
        .flatten()
}

fn const_bool_symbol_value(symbol_type: PineType, value: Option<bool>) -> Option<bool> {
    (symbol_type.qualifier == Qualifier::Const && symbol_type.kind == ValueKind::Bool)
        .then_some(value)
        .flatten()
}

fn const_color_symbol_value(symbol_type: PineType, value: Option<u32>) -> Option<u32> {
    (symbol_type.qualifier == Qualifier::Const && symbol_type.kind == ValueKind::Color)
        .then_some(value)
        .flatten()
}

fn can_reassign(target_type: PineType, value_type: PineType) -> bool {
    if can_assign(target_type, value_type) {
        return true;
    }
    if target_type.kind == ValueKind::Na || value_type.kind == ValueKind::Na {
        return false;
    }
    can_assign(
        PineType::new(Qualifier::Series, target_type.kind),
        value_type,
    )
}

fn reassigned_symbol_type(target_type: PineType, value_type: PineType) -> PineType {
    PineType::new(
        strongest_qualifier(target_type.qualifier, value_type.qualifier),
        common_kind(target_type.kind, value_type.kind).unwrap_or(target_type.kind),
    )
}

fn typed_na_scalar_reassigned_symbol_type(target_type: PineType, value_type: PineType) -> PineType {
    PineType::new(
        value_type.qualifier,
        common_kind(target_type.kind, value_type.kind).unwrap_or(target_type.kind),
    )
}

fn is_scalar_assignment_kind(kind: ValueKind) -> bool {
    matches!(
        kind,
        ValueKind::Int
            | ValueKind::Float
            | ValueKind::Bool
            | ValueKind::String
            | ValueKind::Color
            | ValueKind::Na
    )
}
